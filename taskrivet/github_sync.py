"""Durable GitHub observations and explicit public-summary outbox.

Remote text is evidence, never executable instructions. No automatic ticket creation,
merge, close, checkout, model call, or credential copying occurs here.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import shutil
import subprocess
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode


def repository(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',value):
        raise ValueError('Use owner/repository')
    return value


def gh(endpoint, method='GET', payload=None):
    executable = shutil.which('gh') or next((p for p in ('/opt/homebrew/bin/gh', '/usr/local/bin/gh') if os.access(p, os.X_OK)), None)
    if not executable:raise ValueError('GitHub CLI is required; install and authenticate gh')
    args=[executable,'api','--method',method,endpoint,'-H','Accept: application/vnd.github+json']
    if payload is not None:args+=['--input','-']
    result=subprocess.run(args,input=None if payload is None else json.dumps(payload),text=True,capture_output=True,timeout=30)
    if result.returncode:raise ValueError('GitHub request failed; check gh authentication, repository permission, and rate limits')
    if len(result.stdout)>16*1024*1024:raise ValueError('GitHub response exceeded limit')
    return json.loads(result.stdout)


def classify(kind,row):
    if kind=='runs' and row.get('conclusion') in ('failure','timed_out','action_required'):return 'investigate_failed_check'
    if kind in ('pulls','commits','review_comments'):return 'review_code_change'
    if kind=='issues':return 'reconcile_ticket_change'
    if kind=='comments':return 'review_external_feedback'
    if kind=='releases':return 'verify_release_artifacts'
    return 'inspect_repository_activity'


class GitHubSync:
    def __init__(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.db=sqlite3.connect(path,timeout=5);self.db.row_factory=sqlite3.Row;os.chmod(path,0o600)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS observations(repo TEXT,kind TEXT,identity TEXT,revision TEXT,observed REAL,summary TEXT,action TEXT,url TEXT,PRIMARY KEY(repo,kind,identity,revision));
        CREATE TABLE IF NOT EXISTS cursors(repo TEXT,kind TEXT,since TEXT,PRIMARY KEY(repo,kind));
        CREATE TABLE IF NOT EXISTS polls(id INTEGER PRIMARY KEY,repo TEXT,at REAL,coverage TEXT);
        CREATE TABLE IF NOT EXISTS outbox(repo TEXT,issue INTEGER,key TEXT,body_hash TEXT,state TEXT,url TEXT,PRIMARY KEY(repo,key));
        ''')
    def close(self):self.db.close()
    def poll(self,repo,fetch=gh,max_pages=10):
        repository(repo)
        if type(max_pages)is not int or not 1<=max_pages<=20:raise ValueError('Invalid page bound')
        started=datetime.now(timezone.utc);coverage={};added=0
        feeds={'issues':'issues','comments':'issues/comments','pulls':'pulls','review_comments':'pulls/comments','releases':'releases','runs':'actions/runs','commits':'commits','events':'events'}
        for kind,path in feeds.items():
            cursor=self.db.execute('SELECT since FROM cursors WHERE repo=? AND kind=?',(repo,kind)).fetchone()
            incremental=kind in ('issues','comments','review_comments','commits')
            params={'per_page':100}
            if kind in ('issues','pulls'):params.update(state='all',sort='updated',direction='desc')
            if kind in ('comments','review_comments'):params.update(sort='updated',direction='desc')
            if cursor and incremental:params['since']=cursor['since']
            complete=False;seen=0;error=None
            try:
                for page in range(1,(min(max_pages,3) if kind=='events' else max_pages)+1):
                    data=fetch(f'repos/{repo}/{path}?'+urlencode({**params,'page':page}))
                    rows=data.get('workflow_runs') if kind=='runs' and isinstance(data,dict) else data
                    if not isinstance(rows,list):raise ValueError('Unsupported GitHub response')
                    for row in rows:
                        if not isinstance(row,dict):raise ValueError('Malformed GitHub row')
                        identity=str(row.get('id') or row.get('sha') or '')
                        if not identity:raise ValueError('GitHub identity missing')
                        revision=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
                        summary=str(row.get('title') or row.get('name') or row.get('type') or row.get('commit',{}).get('message') or kind)[:300]
                        url=str(row.get('html_url') or '')
                        if not url.startswith('https://github.com/'+repo+'/'):url='https://github.com/'+repo
                        cur=self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?,?)',(repo,kind,identity,revision,time.time(),summary,classify(kind,row),url));added+=cur.rowcount
                    seen+=len(rows)
                    if len(rows)<100:complete=True;break
                # Commit partial observations, but never advance an incomplete cursor.
                if complete and incremental:self.db.execute('INSERT OR REPLACE INTO cursors VALUES(?,?,?)',(repo,kind,(started-timedelta(minutes=5)).isoformat().replace('+00:00','Z')))
                self.db.commit()
            except (ValueError,OSError,subprocess.SubprocessError) as exc:
                self.db.commit();error=type(exc).__name__
            coverage[kind]={'returned':seen,'page_complete':complete,'error':error,'history_complete':False,'incremental':bool(cursor and incremental)}
        self.db.execute('INSERT INTO polls(repo,at,coverage) VALUES(?,?,?)',(repo,time.time(),json.dumps(coverage)));self.db.commit()
        return {'repo':repo,'new_observations':added,'coverage':coverage,'all_activity_guaranteed':False,'automatic_execution':False}
    def status(self,repo):
        repository(repo)
        poll=self.db.execute('SELECT at,coverage FROM polls WHERE repo=? ORDER BY id DESC LIMIT 1',(repo,)).fetchone()
        rows=self.db.execute('SELECT kind,summary,action,url,observed FROM observations WHERE repo=? ORDER BY observed DESC LIMIT 30',(repo,)).fetchall()
        counts={r[0]:r[1] for r in self.db.execute('SELECT action,COUNT(*) FROM observations WHERE repo=? GROUP BY action',(repo,))}
        return {'repo':repo,'last_poll':poll['at'] if poll else None,'coverage':json.loads(poll['coverage']) if poll else {},'responses':counts,'recent':[dict(r) for r in rows],'all_activity_guaranteed':False,'dispatch_enabled':False}
    def publish(self,repo,issue,key,body,fetch=gh):
        repository(repo)
        if type(issue)is not int or issue<1 or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',key):raise ValueError('Invalid public summary identity')
        if not isinstance(body,str) or not body.strip() or len(body)>12000:raise ValueError('Invalid public summary')
        actor=fetch('user').get('login')
        if not actor:raise ValueError('Authenticated GitHub identity unavailable')
        digest=hashlib.sha256(body.encode()).hexdigest();marker=f'<!-- taskrivet:{key}:{digest} -->';exact=body+'\n\n'+marker
        self.db.execute('BEGIN IMMEDIATE')
        old=self.db.execute('SELECT * FROM outbox WHERE repo=? AND key=?',(repo,key)).fetchone()
        if old and (old['body_hash']!=digest or old['issue']!=issue):self.db.rollback();raise ValueError('Publication key is bound to different content or issue')
        if old and old['state']=='confirmed':self.db.rollback();return {'state':'confirmed','url':old['url'],'reused':True}
        # A previous uncertain send is reconciled, never blindly resent.
        self.db.execute('INSERT OR IGNORE INTO outbox VALUES(?,?,?,?,?,?)',(repo,issue,key,digest,'reserved',None));self.db.commit()
        for page in range(1,21):
            comments=fetch(f'repos/{repo}/issues/{issue}/comments?per_page=100&page={page}')
            for comment in comments:
                if comment.get('body')==exact and comment.get('user',{}).get('login')==actor:
                    url=comment['html_url'];self.db.execute('UPDATE outbox SET state=?,url=? WHERE repo=? AND key=?',('confirmed',url,repo,key));self.db.commit();return {'state':'confirmed','url':url,'reconciled':True}
            if len(comments)<100:break
        else:raise ValueError('Comment reconciliation exceeded bound; nothing sent')
        if old:raise ValueError('Previous send outcome unknown; no automatic resend')
        # Mark sending before network I/O, under a single-writer transaction.
        self.db.execute('BEGIN IMMEDIATE')
        changed=self.db.execute("UPDATE outbox SET state='sending' WHERE repo=? AND key=? AND state='reserved'",(repo,key)).rowcount;self.db.commit()
        if changed!=1:raise ValueError('Another publisher owns this operation')
        response=fetch(f'repos/{repo}/issues/{issue}/comments','POST',{'body':exact})
        confirm=fetch(f'repos/{repo}/issues/comments/{response["id"]}')
        if confirm.get('body')!=exact or confirm.get('user',{}).get('login')!=actor:raise ValueError('Publication readback mismatch')
        self.db.execute('UPDATE outbox SET state=?,url=? WHERE repo=? AND key=?',('confirmed',confirm['html_url'],repo,key));self.db.commit()
        return {'state':'confirmed','url':confirm['html_url'],'reused':False}

"""App-open-only reconciliation for one explicitly configured repository mapping."""
import fcntl,json,os,subprocess,sys,time
from pathlib import Path
from .github_sync import GitHubSync,repository

def cycle(config_path):
    p=Path(config_path);st=p.lstat()
    if p.is_symlink() or st.st_uid!=os.getuid() or st.st_mode&0o077:raise ValueError('Bridge config must be private and owned by you')
    cfg=json.loads(p.read_text());repo=repository(cfg['repo'])
    if cfg.get('enabled') is not True:return {'state':'disabled'}
    with open(p.with_suffix('.lock'),'a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'state':'already_running'}
        sync=GitHubSync(cfg['sync_db'])
        try:poll=sync.poll(repo,max_pages=20)
        finally:sync.close()
        result={'state':'observed','at':time.time(),'poll':poll,'dashboard_readback':False}
        try:
            args=[sys.executable,'-m','taskrivet.dashboard_bridge','--adapter',cfg['adapter'],'--ticket',str(cfg['ticket']),'--repo',repo,'--sync-db',cfg['sync_db']]
            run=subprocess.run(args,capture_output=True,text=True,timeout=30)
            if run.returncode:raise ValueError('Dashboard reconciliation failed; source state preserved')
            receipt=json.loads(run.stdout);result['dashboard_readback']=receipt['dashboard_readback']
        except (ValueError,OSError,subprocess.SubprocessError):result['state']='dashboard_reconciliation_failed'
        target=p.with_suffix('.receipt.json');temp=target.with_suffix('.tmp')
        with open(temp,'w') as f:os.chmod(temp,0o600);json.dump(result,f,indent=2)
        os.replace(temp,target)
        return result

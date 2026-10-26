'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

// electron-builder 26.15.3 calls afterExtract after installAppDependencies,
// before copyAppFiles creates the ASAR and its integrity data. beforePack is
// too early (a rebuild would replace our changes); afterPack is too late.
exports.default = async function stripNativePaths(context) {
  if (!['darwin', 'mas'].includes(context.electronPlatformName)) return;
  if (process.platform !== 'darwin') throw new Error('Native Mac packaging requires macOS strip and codesign');

  const appDir = fs.realpathSync(context.packager.info.appDir);
  const release = path.join(appDir, 'node_modules', 'node-pty', 'build', 'Release');
  const prefixes = [...new Set([os.homedir(), appDir, context.packager.projectDir])]
    .filter(value => typeof value === 'string' && value.length > 1)
    .map(value => Buffer.from(value));

  // These are the two rebuilt Mach-O files shipped by the pinned node-pty
  // dependency. Fail if its layout changes instead of silently skipping it.
  for (const name of ['pty.node', 'spawn-helper']) {
    const binary = path.join(release, name);
    const info = fs.lstatSync(binary);
    if (!info.isFile() || info.size < 4 || info.size > 16 * 1024 * 1024) {
      throw new Error(`Unexpected node-pty native binary: ${name}`);
    }
    const magic = fs.readFileSync(binary).readUInt32BE(0);
    if (![0xfeedface, 0xcefaedfe, 0xfeedfacf, 0xcffaedfe, 0xcafebabe, 0xbebafeca].includes(magic)) {
      throw new Error(`Expected a Mach-O node-pty binary: ${name}`);
    }
    // Remove debug symbols only; retain the native module's exported symbols.
    execFileSync('/usr/bin/strip', ['-S', binary], {stdio: 'pipe'});
    // Stripping invalidates the linker's existing ad-hoc signature. Restore it
    // before archiving; final application signing remains builder-owned.
    execFileSync('/usr/bin/codesign', ['--force', '--sign', '-', binary], {stdio: 'pipe'});
    execFileSync('/usr/bin/codesign', ['--verify', '--strict', binary], {stdio: 'pipe'});
    const cleaned = fs.readFileSync(binary);
    if (prefixes.some(prefix => cleaned.includes(prefix))) {
      throw new Error(`Private build path remains in node-pty binary: ${name}`);
    }
  }
  console.log('  • stripped local debug paths from node-pty native binaries before ASAR creation');
};

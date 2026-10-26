'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {execFileSync} = require('node:child_process');

function readNativeBinary(binary, name) {
  const fd = fs.openSync(binary, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const info = fs.fstatSync(fd);
    if (!info.isFile() || info.size < 4 || info.size > 16 * 1024 * 1024) {
      throw new Error(`Unexpected node-pty native binary: ${name}`);
    }
    // One extra byte detects growth without an unbounded allocation/read.
    const bytes = Buffer.alloc(info.size + 1);
    let size = 0;
    while (size < bytes.length) {
      const count = fs.readSync(fd, bytes, size, bytes.length - size, null);
      if (count === 0) break;
      size += count;
    }
    if (size !== info.size) throw new Error(`Native binary size changed during read: ${name}`);
    return bytes.subarray(0, size);
  } finally {
    fs.closeSync(fd);
  }
}

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
    const magic = readNativeBinary(binary, name).readUInt32BE(0);
    if (![0xfeedface, 0xcefaedfe, 0xfeedfacf, 0xcffaedfe, 0xcafebabe, 0xbebafeca].includes(magic)) {
      throw new Error(`Expected a Mach-O node-pty binary: ${name}`);
    }
    // Remove debug symbols only; retain the native module's exported symbols.
    // External tools still use paths in the trusted, same-user build directory;
    // descriptor validation protects reads, not concurrent tool-path replacement.
    execFileSync('/usr/bin/strip', ['-S', binary], {stdio: 'pipe'});
    // Stripping invalidates the linker's existing ad-hoc signature. Restore it
    // before archiving; final application signing remains builder-owned.
    execFileSync('/usr/bin/codesign', ['--force', '--sign', '-', binary], {stdio: 'pipe'});
    execFileSync('/usr/bin/codesign', ['--verify', '--strict', binary], {stdio: 'pipe'});
    const cleaned = readNativeBinary(binary, name);
    if (prefixes.some(prefix => cleaned.includes(prefix))) {
      throw new Error(`Private build path remains in node-pty binary: ${name}`);
    }
  }
  console.log('  • stripped local debug paths from node-pty native binaries before ASAR creation');
};

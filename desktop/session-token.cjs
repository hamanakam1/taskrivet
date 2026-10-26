'use strict';

const fs = require('node:fs');

const MAX_TOKEN_BYTES = 4096;

function readSessionToken(tokenPath) {
  const {O_RDONLY, O_NOFOLLOW, O_NONBLOCK} = fs.constants;
  if (typeof O_NOFOLLOW !== 'number' || typeof O_NONBLOCK !== 'number' || typeof process.getuid !== 'function') {
    throw new Error('Safe session token reads require POSIX file support');
  }

  // Validate and read the same opened file. A pathname replacement must not
  // redirect the read; nonblocking open lets us reject a FIFO without waiting.
  // Same-user processes remain trusted and can still modify an open file.
  const fd = fs.openSync(tokenPath, O_RDONLY | O_NOFOLLOW | O_NONBLOCK);
  try {
    const st = fs.fstatSync(fd);
    if (!st.isFile() || st.uid !== process.getuid() || (st.mode & 0o077) ||
        st.size < 1 || st.size > MAX_TOKEN_BYTES) {
      throw new Error('Unsafe session token');
    }
    const bytes = Buffer.alloc(MAX_TOKEN_BYTES + 1);
    let count = 0;
    while (count < bytes.length) {
      const read = fs.readSync(fd, bytes, count, bytes.length - count, null);
      if (read === 0) break;
      count += read;
    }
    // The file can grow after fstat; the read itself must stay bounded too.
    if (count < 1 || count > MAX_TOKEN_BYTES) throw new Error('Unsafe session token');
    return bytes.toString('utf8', 0, count);
  } finally {
    fs.closeSync(fd);
  }
}

module.exports = {readSessionToken, MAX_TOKEN_BYTES};

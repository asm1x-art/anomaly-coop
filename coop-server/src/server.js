import net from 'node:net';
import { M, PROTOCOL_VERSION, encode, createDecoder, readStringZ } from './protocol.js';

export function startServer({ port = 7777, host = '0.0.0.0', log = console.log } = {}) {
  let nextId = 1;
  const clients = new Map(); // id -> { socket, name }

  const server = net.createServer((socket) => {
    socket.setNoDelay(true);
    const id = nextId++;
    const addr = `${socket.remoteAddress}:${socket.remotePort}`;
    let name = null;

    const send = (type, payload) => socket.write(encode(type, payload));

    const handle = (type, payload) => {
      switch (type) {
        case M.HELLO: {
          const version = payload.readUInt16LE(0);
          if (version !== PROTOCOL_VERSION) {
            log(`[${id}] protocol mismatch: client ${version}, server ${PROTOCOL_VERSION}`);
            socket.destroy();
            return;
          }
          name = readStringZ(payload, 2);
          clients.set(id, { socket, name });
          log(`[${id}] '${name}' joined from ${addr} (${clients.size} online)`);
          const welcome = Buffer.alloc(4);
          welcome.writeUInt32LE(id, 0);
          send(M.WELCOME, welcome);
          break;
        }
        case M.PING:
          send(M.PONG, payload.subarray(0, 4));
          break;
        default:
          log(`[${id}] unknown message type ${type}`);
      }
    };

    const decode = createDecoder(handle);
    socket.on('data', (chunk) => {
      try {
        decode(chunk);
      } catch (e) {
        log(`[${id}] ${e.message}, dropping`);
        socket.destroy();
      }
    });
    socket.on('error', () => {}); // 'close' follows and reports
    socket.on('close', () => {
      if (clients.delete(id)) log(`[${id}] '${name}' left (${clients.size} online)`);
    });
  });

  return new Promise((resolve) => {
    server.listen(port, host, () => {
      log(`coop server listening on ${host}:${server.address().port}`);
      resolve(server);
    });
  });
}

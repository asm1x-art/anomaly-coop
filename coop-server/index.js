import { startServer } from './src/server.js';

const port = Number(process.env.COOP_PORT ?? 7777);
startServer({ port });

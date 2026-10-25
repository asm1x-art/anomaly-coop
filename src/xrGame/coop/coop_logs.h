#pragma once

// The game's logs and crash dumps go to the co-op server, so a problem in a friend's game can be looked at
// (coop-server keeps them in data/logs/<player>/, the admin page lists them). Each session's log is kept
// (xrCore/log.cpp), and on every connection the ones not sent yet go, a few chunks a frame, compressed.
namespace coop
{
	void update_log_upload(); // per frame while connected
	void send_logs_now();     // console coop_send_logs: this session's log too, and everything not sent
}

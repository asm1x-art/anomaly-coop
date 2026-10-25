#include "stdafx.h"
#include "coop_logs.h"
#include "coop_net.h"
#include "coop_save.h"
#include <future>

#define MINIZ_NO_ZLIB_COMPATIBLE_NAMES // the zlib names would be macros in this file
#include "../../3rd party/optick-git/src/optick_miniz.h" // compiled into the profiler library, linked in already

LPCSTR log_name(); // xrCore/log.cpp: "xray_<user>.log"

namespace coop
{
	static const u32 CHUNK = 14000;          // data per M_LOG, fits a NET_Packet with the name and sizes
	static const u32 CHUNKS_PER_FRAME = 2;   // the game goes on while they go
	static const u32 MAX_PER_CONNECTION = 30; // files sent per connection at most, the oldest first
	static LPCSTR SENT = "_sent";            // a sent file's name ends so: X.log -> X_sent.log

	struct SUpload
	{
		xr_string path;      // the file
		xr_string name;      // as the server keeps it
		bool mark_sent;      // renamed to ..._sent once sent (not this session's log, still being written)
		bool packed = false; // read and compressed when its turn comes (on a worker; set here once it's done)
		u32 raw = 0;
		xr_vector<u8> data;  // compressed
		u32 offset = 0;
	};

	static xr_deque<SUpload> g_queue;   // only added to at the back: the front's packing keeps its reference
	static bool g_scanned = false;      // this connection's files are queued
	static std::future<bool> g_packing; // the front being read and compressed on a worker thread

	static void logs_dir(string_path& dir)
	{
		FS.update_path(dir, "$logs$", "");
	}

	static bool read_file(LPCSTR path, xr_vector<u8>& data)
	{
		FILE* f = fopen(path, "rb");
		if (!f)
			return false;
		fseek(f, 0, SEEK_END);
		data.resize(ftell(f));
		fseek(f, 0, SEEK_SET);
		const bool ok = data.empty() || fread(data.data(), 1, data.size(), f) == data.size();
		fclose(f);
		return ok;
	}

	static void* mz_alloc(void*, size_t items, size_t size)
	{
		return xr_malloc(items * size);
	}

	static void mz_free(void*, void* address)
	{
		xr_free(address);
	}

	// zlib format, as the server's zlib inflates it; miniz here is built without its own malloc
	static bool compress(const xr_vector<u8>& in, xr_vector<u8>& out)
	{
		mz_stream s = {};
		s.zalloc = mz_alloc;
		s.zfree = mz_free;
		if (mz_deflateInit(&s, MZ_DEFAULT_COMPRESSION) != MZ_OK)
			return false;
		out.resize(mz_deflateBound(&s, mz_ulong(in.size())));
		s.next_in = in.data();
		s.avail_in = u32(in.size());
		s.next_out = out.data();
		s.avail_out = u32(out.size());
		const int result = mz_deflate(&s, MZ_FINISH);
		out.resize(s.total_out);
		mz_deflateEnd(&s);
		return result == MZ_STREAM_END;
	}

	static void queue(LPCSTR path, const xr_string& name, bool mark_sent)
	{
		SUpload upload;
		upload.path = path;
		upload.name = name;
		upload.mark_sent = mark_sent;
		g_queue.push_back(std::move(upload));
	}

	static bool pack(SUpload& upload)
	{
		xr_vector<u8> raw;
		if (!read_file(upload.path.c_str(), raw) || raw.empty() || !compress(raw, upload.data))
		{
			Msg("! [coop] %s can't be read or packed: not sent", upload.name.c_str());
			return false;
		}
		upload.raw = u32(raw.size());
		return true; // packed is the main thread's to set, once it has the result
	}

	static xr_vector<xr_string> find(LPCSTR mask)
	{
		string_path dir, pattern;
		logs_dir(dir);
		xr_sprintf(pattern, "%s%s", dir, mask);
		xr_vector<xr_string> names;
		WIN32_FIND_DATAA found;
		HANDLE h = FindFirstFileA(pattern, &found);
		if (h != INVALID_HANDLE_VALUE)
		{
			do
				if (!strstr(found.cFileName, SENT))
					names.push_back(found.cFileName);
			while (FindNextFileA(h, &found));
			FindClose(h);
		}
		std::sort(names.begin(), names.end());
		return names;
	}

	// the earlier sessions' logs (xrCore/log.cpp keeps them as <stem>_<time>.log) and crash dumps not sent yet
	static void scan()
	{
		string_path stem, mask, dir;
		xr_strcpy(stem, log_name());
		if (char* ext = strrchr(stem, '.'))
			*ext = 0;
		xr_sprintf(mask, "%s_*.log", stem);
		xr_vector<xr_string> files = find(mask);
		for (const xr_string& dump : find("*.mdmp"))
			files.push_back(dump);
		logs_dir(dir);
		u32 queued = 0;
		for (const xr_string& name : files)
		{
			if (queued == MAX_PER_CONNECTION)
				break;
			string_path path;
			xr_sprintf(path, "%s%s", dir, name.c_str());
			queue(path, name, true);
			++queued;
		}
		if (queued)
			Msg("[coop] %u log(s) and crash dump(s) of earlier sessions to send to the server", queued);
	}

	static void mark_sent(const xr_string& path)
	{
		string_path sent;
		xr_strcpy(sent, path.c_str());
		char* ext = strrchr(sent, '.');
		const xr_string extension = ext ? ext : "";
		if (ext)
			*ext = 0;
		xr_strcat(sent, SENT);
		xr_strcat(sent, extension.c_str());
		MoveFileExA(path.c_str(), sent, MOVEFILE_REPLACE_EXISTING);
	}

	void update_log_upload()
	{
		if (!is_connected())
		{
			if (g_packing.valid())
				g_packing.wait(); // it works on the queue's front
			g_packing = {};
			g_scanned = false;
			g_queue.clear();
			return;
		}
		if (world_busy())
			return; // not while the world downloads or loads: those frames are the loading's
		if (!g_scanned)
		{
			g_scanned = true;
			scan();
		}
		for (u32 i = 0; i < CHUNKS_PER_FRAME && !g_queue.empty(); ++i)
		{
			SUpload& upload = g_queue.front();
			if (!upload.packed)
			{
				// read and compressed aside, the game doesn't wait a frame for it
				if (!g_packing.valid())
				{
					SUpload* target = &upload; // the element itself: a captured reference variable is not
					g_packing = std::async(std::launch::async, [target] { return pack(*target); });
				}
				if (g_packing.wait_for(std::chrono::seconds(0)) != std::future_status::ready)
					return;
				if (!g_packing.get())
				{
					g_queue.pop_front();
					continue;
				}
				upload.packed = true;
			}
			const u32 total = u32(upload.data.size());
			NET_Packet P;
			P.w_begin(M_LOG);
			P.w_stringZ(upload.name.c_str());
			P.w_u32(upload.raw);
			P.w_u32(total);
			P.w_u32(upload.offset);
			const u32 size = _min(CHUNK, total - upload.offset);
			P.w(upload.data.data() + upload.offset, size);
			send(P);
			upload.offset += size;
			if (upload.offset < total)
				continue;
			Msg("[coop] %s sent to the server (%u bytes, %u packed)", upload.name.c_str(), upload.raw, total);
			if (upload.mark_sent)
				mark_sent(upload.path);
			g_queue.pop_front();
		}
	}

	void send_logs_now()
	{
		if (!is_connected())
		{
			Msg("! [coop] not connected: the logs go the next time we are");
			return;
		}
		FlushLog();
		string_path dir, path, stem;
		logs_dir(dir);
		xr_sprintf(path, "%s%s", dir, log_name());
		xr_strcpy(stem, log_name());
		if (char* ext = strrchr(stem, '.'))
			*ext = 0;
		SYSTEMTIME t;
		GetLocalTime(&t);
		string_path name;
		xr_sprintf(name, "%s_%04u-%02u-%02u_%02u-%02u-%02u_current.log", stem, t.wYear, t.wMonth, t.wDay, t.wHour,
		           t.wMinute, t.wSecond);
		queue(path, name, false);
		if (!g_scanned)
		{
			g_scanned = true;
			scan();
		}
		Msg("[coop] sending the logs: %u file(s)", u32(g_queue.size()));
	}
}

#include "stdafx.h"
#include "grass_occlusion.h"
#include "Level.h"
#include "../Layers/xrRender/DetailFormat.h"
#include <mutex>

int g_ai_grass = 1;

namespace grass_occlusion
{
	namespace
	{
		struct slot
		{
			float ground;
			float top;
			float density; // 0..1
		};

		struct settings
		{
			bool enabled = false;
			float depth = 8.f;
			float step = 0.5f;
			float k = 0.25f;
			float max_height = 1.2f;
		};

		std::mutex guard;
		shared_str loaded_level;
		settings cfg;
		int offs_x = 0, offs_z = 0;
		u32 size_x = 0, size_z = 0;
		xr_vector<slot> slots;

		void read_settings()
		{
			const LPCSTR S = "ai_grass";
			cfg = settings();
			if (!pSettings->section_exist(S))
				return;
			cfg.enabled = READ_IF_EXISTS(pSettings, r_bool, S, "enabled", false);
			cfg.depth = READ_IF_EXISTS(pSettings, r_float, S, "depth", cfg.depth);
			cfg.step = _max(0.1f, READ_IF_EXISTS(pSettings, r_float, S, "step", cfg.step));
			cfg.k = READ_IF_EXISTS(pSettings, r_float, S, "k", cfg.k);
			cfg.max_height = READ_IF_EXISTS(pSettings, r_float, S, "max_height", cfg.max_height);
		}

		void load(const shared_str& level)
		{
			loaded_level = level;
			slots.clear();
			size_x = size_z = 0;
			read_settings();
			if (!cfg.enabled || !FS.exist("$level$", "level.details"))
				return;

			string_path fn;
			FS.update_path(fn, "$level$", "level.details");
			IReader* F = FS.r_open(fn);
			if (!F)
				return;

			DetailHeader H;
			if (!F->r_chunk_safe(0, &H, sizeof(H)) || (H.version != DETAIL_VERSION_3 && H.version != DETAIL_VERSION_4))
			{
				FS.r_close(F);
				return;
			}

			// models: rocks and the like (no waving) do not hide anyone
			xr_vector<u8> grass;
			grass.resize(H.object_count, 1);
			if (IReader* M = F->open_chunk(1))
			{
				for (u32 i = 0; i < H.object_count; ++i)
				{
					if (IReader* O = M->open_chunk(i))
					{
						string256 s;
						O->r_stringZ(s, sizeof(s));
						O->r_stringZ(s, sizeof(s));
						grass[i] = (O->r_u32() & DO_NO_WAVING) ? 0 : 1;
						O->close();
					}
				}
				M->close();
			}

			IReader* R = F->open_chunk(2);
			if (!R)
			{
				FS.r_close(F);
				return;
			}
			const u32 count = H.size_x * H.size_z;
			const bool v4 = H.version == DETAIL_VERSION_4;
			if (R->length() < count * (v4 ? sizeof(DetailSlot) : sizeof(DetailSlot_v3)))
			{
				R->close();
				FS.r_close(F);
				return;
			}
			slots.resize(count);
			u32 with_grass = 0;
			for (u32 i = 0; i < count; ++i)
			{
				DetailSlot D;
				if (v4)
					R->r(&D, sizeof(D));
				else
				{
					DetailSlot_v3 D3;
					R->r(&D3, sizeof(D3));
					expand_v3(D, D3);
				}
				float density = 0.f;
				for (u32 o = 0; o < 4; ++o)
				{
					const u16 id = D.r_id(o);
					if (id == DetailSlot::ID_Empty || id >= H.object_count || !grass[id])
						continue;
					const DetailPalette& p = D.palette[o];
					density += float(p.a0 + p.a1 + p.a2 + p.a3) / 60.f;
				}
				slot& s = slots[i];
				s.ground = D.r_ybase();
				s.top = s.ground + _min(D.r_yheight(), cfg.max_height);
				s.density = _min(density, 1.f);
				if (s.density > 0.f)
					++with_grass;
			}
			R->close();
			FS.r_close(F);
			offs_x = H.offs_x;
			offs_z = H.offs_z;
			size_x = H.size_x;
			size_z = H.size_z;
			Msg("* [ai_grass] %s: %u of %u slots with grass", level.c_str(), with_grass, count);
		}

		const slot* at(const Fvector& p)
		{
			const int x = iFloor(p.x / DETAIL_SLOT_SIZE) + offs_x;
			const int z = iFloor(p.z / DETAIL_SLOT_SIZE) + offs_z;
			if (x < 0 || z < 0 || u32(x) >= size_x || u32(z) >= size_z)
				return nullptr;
			return &slots[u32(z) * size_x + u32(x)];
		}
	}

	float transparency(const Fvector& from, const Fvector& to)
	{
		if (!g_pGameLevel || !g_ai_grass)
			return 1.f;
		{
			std::lock_guard<std::mutex> lock(guard);
			const shared_str& level = Level().name();
			if (loaded_level != level)
				load(level);
		}
		if (slots.empty())
			return 1.f;

		Fvector dir;
		dir.sub(from, to);
		const float length = dir.magnitude();
		if (length < EPS_L)
			return 1.f;
		dir.div(length);

		float vis = 1.f;
		const float end = _min(cfg.depth, length);
		for (float t = cfg.step * 0.5f; t < end; t += cfg.step)
		{
			Fvector p;
			p.mad(to, dir, t);
			const slot* s = at(p);
			if (!s || s->density <= 0.f || p.y < s->ground - 0.3f || p.y > s->top)
				continue;
			vis *= _max(0.f, 1.f - cfg.k * s->density * cfg.step);
			if (vis < 0.01f)
				return 0.f;
		}
		return vis;
	}
}

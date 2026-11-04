// xrCDB.cpp : Defines the entry point for the DLL application.
//

#include "stdafx.h"
#pragma hdrstop

#include "xrCDB.h"
#include <thread>
#include "profiler.h"

#ifdef USE_ARENA_ALLOCATOR
static const u32	s_arena_size = (128+16)*1024*1024;
static char			s_fake_array[s_arena_size];
//doug_lea_allocator	g_collision_allocator( s_fake_array, s_arena_size, "collision" );
#endif // #ifdef USE_ARENA_ALLOCATOR

namespace Opcode
{
#	include "OPC_TreeBuilders.h"
} // namespace Opcode

using namespace CDB;
using namespace Opcode;

//BOOL APIENTRY DllMain( HANDLE hModule, 
BOOL DllMainIgnore1(HANDLE hModule,
                    u32 ul_reason_for_call,
                    LPVOID lpReserved
)
{
	switch (ul_reason_for_call)
	{
	case DLL_PROCESS_ATTACH:
	case DLL_THREAD_ATTACH:
	case DLL_THREAD_DETACH:
	case DLL_PROCESS_DETACH:
		break;
	}
	return TRUE;
}

// Model building
MODEL::MODEL()
#ifdef PROFILE_CRITICAL_SECTIONS
	:cs(MUTEX_PROFILE_ID(MODEL))
#endif // PROFILE_CRITICAL_SECTIONS
{
	tree = 0;
	tris = 0;
	tris_count = 0;
	verts = 0;
	verts_count = 0;
	status = S_INIT;
}

MODEL::~MODEL()
{
	syncronize(); // maybe model still in building
	status = S_INIT;
	CDELETE(tree);
	CFREE(tris);
	tris_count = 0;
	CFREE(verts);
	verts_count = 0;
}

struct BTHREAD_params
{
	MODEL* M;
	Fvector* V;
	int Vcnt;
	TRI* T;
	int Tcnt;
	build_callback* BC;
	void* BCP;
};

void MODEL::build_thread(void* params)
{
	PROF_EVENT();

	_initialize_cpu_thread();
	FPU::m64r();
	BTHREAD_params P = *((BTHREAD_params*)params);
	P.M->cs.Enter();
	P.M->build_internal(P.V, P.Vcnt, P.T, P.Tcnt, P.BC, P.BCP);
	P.M->status = S_READY;
	P.M->cs.Leave();
	//Msg						("* xrCDB: cform build completed, memory usage: %d K",P.M->memory()/1024);
}

void MODEL::build(Fvector* V, int Vcnt, TRI* T, int Tcnt, build_callback* bc, void* bcp)
{
	R_ASSERT(S_INIT == status);
	R_ASSERT((Vcnt>=4)&&(Tcnt>=2));

	_initialize_cpu_thread();
#ifdef _EDITOR
	build_internal				(V,Vcnt,T,Tcnt,bc,bcp);
#else
	// The vertices and triangles are copied (and the materials' callback run) now: the caller's arrays may go and the
	// level's code reads ours straight away. The tree (built, or read from the cache) of a big model comes in the
	// background meanwhile, while the level goes on loading; a query before it is there waits (syncronize).
	// -no_async_cdb: build here, as before.
	build_geometry(V, Vcnt, T, Tcnt, bc, bcp);
	if (tris_count >= 20000 && !strstr(Core.Params, "-no_async_cdb"))
	{
		status = S_BUILD;
		std::thread([this]
		{
			_initialize_cpu_thread();
			FPU::m64r();
			build_tree();
			status = S_READY;
		}).detach();
	}
	else
	{
		build_tree();
		status = S_READY;
	}
#endif
}

// Tree cache (after IX-Ray's level_cache): building the OPCODE tree of a level's collision takes 1.5-2 s each load, the
// same every time. A big model's built nodes go to $app_data_root$\cdb_cache\<key>.cdb, the key being a crc of its
// vertices and triangle indices (the tree depends on nothing else); a later build with the same key reads them back.
// Child pointers are stored as node indices (shifted left, bit 0 clear; a leaf's primitive keeps its bit 0 set).
namespace
{
	const u32 CDB_CACHE_MAGIC = 0x43424443; // "CDBC"
	const u32 CDB_CACHE_VERSION = 1;
	const int CDB_CACHE_MIN_TRIS = 20000;

	struct cdb_cache_header
	{
		u32 magic, version, node_size, nodes, key, tris, verts;
	};

	void cdb_cache_name(string_path& out, u32 key, int tris, int verts)
	{
		string128 name;
		xr_sprintf(name, "cdb_cache\\%08x_%d_%d.cdb", key, tris, verts);
		FS.update_path(out, "$app_data_root$", name);
	}

	Opcode::AABBNoLeafNode* cdb_cache_read(LPCSTR file, const cdb_cache_header& want, u32& nodes)
	{
		if (!FS.exist(file))
			return nullptr;
		IReader* R = FS.r_open(file);
		if (!R)
			return nullptr;
		cdb_cache_header H;
		Opcode::AABBNoLeafNode* out = nullptr;
		if (R->length() >= sizeof(H))
		{
			R->r(&H, sizeof(H));
			if (H.magic == want.magic && H.version == want.version && H.node_size == want.node_size && H.key == want.key
				&& H.tris == want.tris && H.verts == want.verts && H.nodes
				&& u32(R->elapsed()) == H.nodes * sizeof(Opcode::AABBNoLeafNode))
			{
				out = CALLOC(Opcode::AABBNoLeafNode, H.nodes);
				R->r(out, H.nodes * sizeof(Opcode::AABBNoLeafNode));
				nodes = H.nodes;
				for (u32 i = 0; i < nodes; i++)
				{
					uintptr_t* d[2] = { &out[i].mData, &out[i].mData2 };
					for (uintptr_t* v : d)
					{
						if (!(*v & 1))
						{
							const uintptr_t index = *v >> 1;
							if (index >= nodes)
							{
								CFREE(out);
								FS.r_close(R);
								return nullptr;
							}
							*v = uintptr_t(out + index);
						}
					}
				}
			}
		}
		FS.r_close(R);
		return out;
	}

	void cdb_cache_write(LPCSTR file, cdb_cache_header H, const Opcode::OPCODE_Model* model)
	{
		const Opcode::AABBNoLeafTree* tree = (const Opcode::AABBNoLeafTree*)model->GetTree();
		const Opcode::AABBNoLeafNode* base = tree->GetNodes();
		H.nodes = tree->GetNbNodes();
		xr_vector<Opcode::AABBNoLeafNode> copy;
		copy.resize(H.nodes);
		CopyMemory(copy.data(), base, H.nodes * sizeof(Opcode::AABBNoLeafNode));
		for (Opcode::AABBNoLeafNode& n : copy)
		{
			uintptr_t* d[2] = { &n.mData, &n.mData2 };
			for (uintptr_t* v : d)
				if (!(*v & 1))
					*v = uintptr_t(((const Opcode::AABBNoLeafNode*)*v) - base) << 1;
		}
		IWriter* W = FS.w_open(file);
		if (!W)
			return;
		W->w(&H, sizeof(H));
		W->w(copy.data(), u32(copy.size() * sizeof(Opcode::AABBNoLeafNode)));
		FS.w_close(W);
	}
}

void MODEL::build_geometry(Fvector* V, int Vcnt, TRI* T, int Tcnt, build_callback* bc, void* bcp)
{
	PROF_EVENT();

	// verts
	verts_count = Vcnt;
	verts = CALLOC(Fvector, verts_count);
	CopyMemory(verts, V, verts_count*sizeof(Fvector));

	// tris
	tris_count = Tcnt;
	tris = CALLOC(TRI, tris_count);
	CopyMemory(tris, T, tris_count*sizeof(TRI));

	// callback
	if (bc) bc(verts, Vcnt, tris, Tcnt, bcp);

	// Release data pointers
	status = S_BUILD;
}

void MODEL::build_internal(Fvector* V, int Vcnt, TRI* T, int Tcnt, build_callback* bc, void* bcp)
{
	build_geometry(V, Vcnt, T, Tcnt, bc, bcp);
	build_tree();
}

void MODEL::build_tree()
{
	PROF_EVENT();

	// Allocate temporary "OPCODE" tris + convert tris to 'pointer' form
	u32* temp_tris = CALLOC(u32, tris_count*3);
	if (0 == temp_tris)
	{
		CFREE(verts);
		CFREE(tris);
		return;
	}
	u32* temp_ptr = temp_tris;
	for (int i = 0; i < tris_count; i++)
	{
		*temp_ptr++ = tris[i].verts[0];
		*temp_ptr++ = tris[i].verts[1];
		*temp_ptr++ = tris[i].verts[2];
	}

	// the tree from the cache, when this geometry was built before
	cdb_cache_header key_header = { CDB_CACHE_MAGIC, CDB_CACHE_VERSION, sizeof(Opcode::AABBNoLeafNode), 0, 0,
		u32(tris_count), u32(verts_count) };
	string_path cache_file = "";
	// off unless -cdb_cache: on a hard disk, reading the cache (118 MB for the Cordon) in the background competes with
	// the textures for the disk, while building the tree there only takes idle CPU time
	if (tris_count >= CDB_CACHE_MIN_TRIS && strstr(Core.Params, "-cdb_cache"))
	{
		CTimer t;
		t.Start();
		key_header.key = crc32(temp_tris, tris_count * 3 * sizeof(u32), crc32(verts, verts_count * sizeof(Fvector)));
		cdb_cache_name(cache_file, key_header.key, tris_count, verts_count);
		u32 nodes = 0;
		if (Opcode::AABBNoLeafNode* cached = cdb_cache_read(cache_file, key_header, nodes))
		{
			tree = CNEW(OPCODE_Model)();
			tree->Restore(cached, nodes);
			CFREE(temp_tris);
			Msg("* xrCDB: %d triangles, the tree from the cache (%u nodes) in %u ms", tris_count, nodes, t.GetElapsed_ms());
			return;
		}
	}

	// Build a non quantized no-leaf tree
	CTimer build_timer;
	build_timer.Start();
	OPCODECREATE OPCC;
	OPCC.NbTris = tris_count;
	OPCC.NbVerts = verts_count;
	OPCC.Tris = (unsigned*)temp_tris;
	OPCC.Verts = (Point*)verts;
	OPCC.Rules = SPLIT_COMPLETE | SPLIT_SPLATTERPOINTS | SPLIT_GEOMCENTER;
	OPCC.NoLeaf = true;
	OPCC.Quantized = false;
	// if (Memory.debug_mode) OPCC.KeepOriginal = true;

	tree = CNEW(OPCODE_Model)();
	if (!tree->Build(OPCC))
	{
		CFREE(verts);
		CFREE(tris);
		CFREE(temp_tris);
		return;
	};

	// Free temporary tris
	CFREE(temp_tris);

	if (tris_count >= CDB_CACHE_MIN_TRIS)
		Msg("* xrCDB: %d triangles, the tree built in %u ms", tris_count, build_timer.GetElapsed_ms());

	if (cache_file[0])
	{
		cdb_cache_write(cache_file, key_header, tree);
		Msg("* xrCDB: %d triangles built, the tree cached in %s", tris_count, cache_file);
	}
	return;
}

u32 MODEL::memory()
{
	if (S_BUILD == status)
	{
		Msg("! xrCDB: model still isn't ready");
		return 0;
	}
	u32 V = verts_count * sizeof(Fvector);
	u32 T = tris_count * sizeof(TRI);
	return tree->GetUsedBytes() + V + T + sizeof(*this) + sizeof(*tree);
}

// This is the constructor of a class that has been exported.
// see xrCDB.h for the class definition
COLLIDER::COLLIDER()
{
	ray_mode = 0;
	box_mode = 0;
	frustum_mode = 0;
}

COLLIDER::~COLLIDER()
{
	r_free();
}

RESULT& COLLIDER::r_add()
{
	rd.push_back(RESULT());
	return rd.back();
}

void COLLIDER::r_free()
{
	rd.clear_and_free();
}

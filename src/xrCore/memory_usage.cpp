#include "stdafx.h"
#include <malloc.h>
#include <errno.h>

XRCORE_API void vminfo(size_t* _free, size_t* reserved, size_t* committed)
{
	MEMORY_BASIC_INFORMATION memory_info;
	memory_info.BaseAddress = 0;
	*_free = *reserved = *committed = 0;
	while (VirtualQuery(memory_info.BaseAddress, &memory_info, sizeof(memory_info)))
	{
		switch (memory_info.State)
		{
		case MEM_FREE:
			*_free += memory_info.RegionSize;
			break;
		case MEM_RESERVE:
			*reserved += memory_info.RegionSize;
			break;
		case MEM_COMMIT:
			*committed += memory_info.RegionSize;
			break;
		}
		memory_info.BaseAddress = (char*)memory_info.BaseAddress + memory_info.RegionSize;
	}
}

XRCORE_API void log_vminfo()
{
	size_t w_free, w_reserved, w_committed;
	vminfo(&w_free, &w_reserved, &w_committed);
	Msg(
		"* [win32]: free[%lld K], reserved[%lld K], committed[%lld K]",
		w_free / 1024,
		w_reserved / 1024,
		w_committed / 1024
	);
}

size_t xrMemory::mem_usage()
{
	// _heapwalk does not lock the heap between its steps: a block another thread frees under the walk (a level's
	// collision tree is built in the background while the loading stages log "phase cmem") reads as a bad node, and
	// that was a fatal error for a number that only goes to the log. The heap is locked for the walk (the CRT's heap
	// is the process heap); a walk that still stops early is only logged.
	HANDLE heap = GetProcessHeap();
	HeapLock(heap);
	_HEAPINFO hinfo = {};
	int status;
	size_t bytesUsed = 0;
	while ((status = _heapwalk(&hinfo)) == _HEAPOK)
	{
		if (hinfo._useflag == _USEDENTRY)
			bytesUsed += hinfo._size;
	}
	HeapUnlock(heap);
	if (status != _HEAPEMPTY && status != _HEAPEND)
		Msg("! xrMemory::mem_usage: the heap walk stopped early (%s), %lld K counted",
			status == _HEAPBADPTR ? "bad pointer to heap" : status == _HEAPBADBEGIN ? "bad start of heap" :
			status == _HEAPBADNODE ? "bad node in heap" : "unknown status", bytesUsed / 1024);
	return bytesUsed;
}

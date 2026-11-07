#pragma once

// NVIDIA DLSS Super Resolution through NGX (the DLSS SDK, src/3rd party/nvngx_dlss, fetched by
// tools/dlss/get_dlss_sdk.ps1; without it the engine builds with DLSS off). The world is drawn at the size NGX asks
// for, jittered (r4_taa.h), with motion vectors and depth (CRenderTarget::phase_dlss_mv); DLSS makes the frame at the
// screen's size from it and the frames before (CRenderTarget::scale_end), the UI is drawn over that.
// Its input is the finished picture (tonemapped, with the post effects): DLSS's LDR mode, no exposure needed.
// The structure follows IX-Ray's DLSSWrapper (Copyright (c) 2019-2025 IX-Ray and contributors, MIT-like
// non-commercial licence: https://github.com/ixray-team/ixray-1.6-stcop), written anew for this engine.
namespace dlss
{
// why DLSS can or cannot run here (r__dlss_status; the options menu shows the reason)
enum class status
{
	ok,
	not_started, // the renderer isn't made yet (the console's dump at the start shows this)
	no_sdk, // the engine was built without the DLSS SDK
	headless, // the co-op host without a window (-coop_host)
	not_nvidia, // another maker's video card
	msaa, // MSAA is on (r3_msaa): they don't go together, it takes a restart
	hdr10, // HDR10 output is on
	no_dll, // nvngx_dlss.dll is not next to the game's exe
	init_failed, // NGX did not start (an old driver, Wine...)
	old_driver, // the driver is too old for DLSS
	unsupported, // the card has no DLSS (not RTX)
};

// modes, r__dlss_mode
enum mode
{
	mode_off,
	mode_dlaa, // the screen's size: anti-aliasing only
	mode_quality,
	mode_balanced,
	mode_performance,
	mode_ultra_performance,
};

// once the device is made (CRender::create); msaa/hdr10: the render's options then. Only the first call after the
// start or shutdown() does anything.
void init(bool msaa, bool hdr10);
void shutdown();

status get_status();
const char* status_name(status s);
bool available();

// the render size NGX recommends for a mode at this screen size; false if it can't tell
bool optimal_size(u32 mode, u32 display_w, u32 display_h, u32& render_w, u32& render_h);

// the DLSS feature for these sizes (with every render target change: CRenderTarget's constructor / destructor)
bool create_feature(u32 mode, u32 render_w, u32 render_h, u32 display_w, u32 display_h);
void release_feature();
bool feature_ready();

// upscale: color, motion vectors (render pixels, to where it was a frame ago), depth at the render size; out at the
// screen's size (with UAV). jitter: the frame's shift in render pixels. reset: the last frames are not this scene.
bool evaluate(ID3D11Resource* color, ID3D11Resource* mv, ID3D11Resource* depth, ID3D11Resource* out, u32 render_w,
              u32 render_h, float jitter_x, float jitter_y, bool reset, float frame_ms);
}

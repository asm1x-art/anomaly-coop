#pragma once

// Sub-pixel camera jitter and motion vectors for temporal upscaling (DLSS).
// Jitter: each frame of the main view is drawn shifted by a fraction of a pixel (the Halton 2,3 sequence); the
// upscaler, told the shift, gathers the frames into one sharper image. The shift goes into the projection
// (Device.mProject and the HUD's), so every shader gets it; what must not move with it (the sun's cascades, the
// previous-frame matrices for motion vectors and motion blur) uses the copies here.
// Motion vectors: where each pixel was a frame ago (CRenderTarget::phase_dlss_mv, shaders dlss_mv.h). The last main
// frame's camera is kept here: the scope's second viewport draws frames of its own in between.
struct r_taa_jitter
{
	bool on = false; // this frame is jittered (stays set after r_taa_jitter_end, for the upscaler)
	bool applied = false; // Device's matrices hold the shift now (between begin and r_taa_jitter_end)
	bool mv = false; // this frame makes motion vectors (models keep their last bones, CSkeletonX)
	Fvector2 px = {0.f, 0.f}; // the shift in render pixels, -0.5..0.5 (x right, y down), as DLSS takes it
	Fvector2 ndc = {0.f, 0.f}; // the same in clip space (x right, y up)
	u32 phases = 0;

	// this frame's matrices without the shift
	Fmatrix proj, full, proj_hud, full_hud;
	// the last main frame's camera, without the shift
	Fmatrix prev_view, prev_proj, prev_proj_hud;
	bool prev_valid = false;
	u32 frame = 0; // main frames drawn (the scope's frames in between don't count)
	bool cut = false; // the camera jumped since the last main frame (a teleport): the upscaler's history is not this scene

	const Fmatrix& project() const { return applied ? proj : Device.mProject; }
	const Fmatrix& full_transform() const { return applied ? full : Device.mFullTransform; }
	const Fmatrix& project_hud() const { return applied ? proj_hud : Device.mProjectHud; }
};

extern r_taa_jitter g_taa;

// A frame of the main view begins: jitter it if wanted (DLSS on, or r__taa_jitter for a test), make motion vectors if
// wanted (DLSS on, or r__dlss_mv_debug). render_w/h: the size it is drawn at; ratio: the screen's size over it.
void r_taa_frame_begin(bool jitter, bool mv, u32 render_w, u32 render_h, float ratio);
// the scene is drawn: Device's matrices without the shift again (what comes after works in screen space)
void r_taa_jitter_end();
// the frame is done: its camera is kept for the next one
void r_taa_frame_end();

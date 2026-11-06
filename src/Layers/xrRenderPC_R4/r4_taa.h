#pragma once

// Sub-pixel camera jitter for temporal upscaling (DLSS). Each frame of the main view is drawn shifted by a fraction
// of a pixel (the Halton 2,3 sequence); the upscaler, told the shift, gathers the frames into one sharper image.
// The shift goes into the projection (Device.mProject and the HUD's), so every shader gets it; what must not move
// with it (the sun's cascades, the previous-frame matrices for motion vectors and motion blur) uses the copies here.
struct r_taa_jitter
{
	bool on = false; // this frame is jittered (stays set after r_taa_jitter_end, for the upscaler)
	bool applied = false; // Device's matrices hold the shift now (between begin and end)
	Fvector2 px = {0.f, 0.f}; // the shift in render pixels, -0.5..0.5 (x right, y down), as DLSS takes it
	Fvector2 ndc = {0.f, 0.f}; // the same in clip space (x right, y up)
	u32 phases = 0;

	// the frame's matrices without the shift
	Fmatrix proj, full, proj_hud, full_hud;

	const Fmatrix& project() const { return applied ? proj : Device.mProject; }
	const Fmatrix& full_transform() const { return applied ? full : Device.mFullTransform; }
	const Fmatrix& project_hud() const { return applied ? proj_hud : Device.mProjectHud; }
};

extern r_taa_jitter g_taa;

// Start jittering this frame if it is wanted (DLSS on, or r__taa_jitter for a test) and it is the main view; render_w/h
// is the size it is drawn at, ratio the screen's size over it (more phases for a bigger ratio)
void r_taa_jitter_begin(bool wanted, u32 render_w, u32 render_h, float ratio);
void r_taa_jitter_end();

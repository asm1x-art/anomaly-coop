#ifndef DLSS_MV_H
#define DLSS_MV_H

// Motion vectors for the DLSS upscaler (engine: r4_taa.h, CRenderTarget::phase_dlss_mv).
// The engine defines DLSS_MV when DLSS can run. Then the G-buffer has a fourth target (rt_ssfx_motion_vectors): models
// (people, monsters, weapons, the hands) write into it how far they moved on the screen since the last frame; all the
// rest writes nothing there (w = 0), and the engine works their motion out from the depth and the camera.
// Format: xy = this frame's screen position minus the last one's, in texture coordinates (y down); w = 1 if written.
// The same layout as Screen Space Shaders' motion vectors, so that mod's shaders can stand in for these.

#ifdef DLSS_MV
uniform float4x4 m_wvp_prev; // the last frame's world-view-projection (for a skinned model: of its last bones)
uniform float4 m_dlss_jitter; // xy: this frame's camera jitter in clip space (taken back out of the position)

// a vertex shader's output without motion (static geometry, grass, trees: the camera's motion covers them)
#define DLSS_MV_NONE(O) { O.vel_curr = 0; O.vel_prev = 0; }
// a vertex shader's output for a moving model: P_prev is the vertex where it was a frame ago (model space)
#define DLSS_MV_SET(O, P_prev) { O.vel_curr = O.hpos; O.vel_curr.xy -= m_dlss_jitter.xy * O.hpos.w; O.vel_prev = mul(m_wvp_prev, P_prev); }

float4 dlss_velocity(float4 curr, float4 prev)
{
	if (curr.w <= 0.0001f || prev.w <= 0.0001f)
		return 0; // no motion of its own (or a frame ago behind the camera): the camera's
	float2 d = curr.xy / curr.w - prev.xy / prev.w;
	return float4(d.x * 0.5f, -d.y * 0.5f, 0, 1);
}

// a pixel shader's G-buffer output (f_deffer O) gets the motion of its input I
#define DLSS_MV_WRITE(O, I) { O.Velocity = dlss_velocity(I.vel_curr, I.vel_prev); }
#else
#define DLSS_MV_NONE(O)
#define DLSS_MV_SET(O, P_prev)
#define DLSS_MV_WRITE(O, I)
#endif

#endif

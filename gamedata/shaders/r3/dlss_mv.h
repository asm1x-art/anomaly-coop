#ifndef DLSS_MV_H
#define DLSS_MV_H

// Motion vectors for the DLSS upscaler (engine: r4_taa.h, CRenderTarget::phase_dlss_mv).
// The engine looks for this file to know the G-buffer shaders write motion vectors, and defines DLSS_MV when DLSS can
// run. The vectors themselves are Screen Space Shaders' (screenspace_mvectors.h): every G-buffer shader writes into the
// fourth target (rt_ssfx_motion_vectors) how far its pixel moved on the screen since the last frame.
// Format: xy = this frame's screen position minus the last one's, in texture coordinates (y down); z = 1 on the HUD
// (hands, weapon); w = SSS's mask for its own TAA.
// What DLSS needs on top of SSS:
//   - the camera jitter taken out of the current position (ssfx_mv_calc, m_dlss_jitter);
//   - the G-buffer shaders SSS left without vectors write the camera's motion (deffer_particle, deffer_detail_*);
//   - dlss_mv.ps turns the target into what DLSS takes (pixels, from this frame to the last) and adds the sky and the
//     HUD's see-through parts.

#endif

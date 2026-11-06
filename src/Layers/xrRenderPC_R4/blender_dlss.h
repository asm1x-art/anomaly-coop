#pragma once

// DLSS's passes (CRenderTarget::phase_dlss_mv, scale_end):
// 0: motion vectors and depth for DLSS from the G-buffer (dlss_mv.ps)
// 1: those motion vectors on the screen, for a test (r__dlss_mv_debug, dlss_mv_debug.ps)
// 2: DLSS's output copied onto the screen (render_scale.ps)
class CBlender_dlss : public IBlender
{
public:
	virtual LPCSTR getComment() { return "DLSS: motion vectors, their view, the output's copy"; }
	virtual BOOL canBeDetailed() { return FALSE; }
	virtual BOOL canBeLMAPped() { return FALSE; }

	virtual void Compile(CBlender_Compile& C);

	CBlender_dlss();
	virtual ~CBlender_dlss();
};

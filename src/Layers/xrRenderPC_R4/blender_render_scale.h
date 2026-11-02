#pragma once

// Render scale: the world is drawn at a lower resolution (r__render_scale) and stretched onto the screen before the
// UI. This blender is that stretch: the scaled frame ($user$render_scale) sampled with a linear filter.
class CBlender_render_scale : public IBlender
{
public:
	virtual LPCSTR getComment() { return "render scale: the scaled frame stretched to the screen"; }
	virtual BOOL canBeDetailed() { return FALSE; }
	virtual BOOL canBeLMAPped() { return FALSE; }

	virtual void Compile(CBlender_Compile& C);

	CBlender_render_scale();
	virtual ~CBlender_render_scale();
};

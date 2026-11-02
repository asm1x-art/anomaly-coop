#include "stdafx.h"

#include "blender_render_scale.h"

CBlender_render_scale::CBlender_render_scale() { description.CLS = 0; }

CBlender_render_scale::~CBlender_render_scale()
{
}

void CBlender_render_scale::Compile(CBlender_Compile& C)
{
	IBlender::Compile(C);

	C.r_Pass("stub_notransform_t", "render_scale", FALSE, FALSE, FALSE);
	C.r_dx10Texture("s_generic", r2_RT_render_scale);
	C.r_dx10Sampler("smp_rtlinear");
	C.r_End();
}

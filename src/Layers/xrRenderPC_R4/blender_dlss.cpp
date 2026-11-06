#include "stdafx.h"

#include "blender_dlss.h"

CBlender_dlss::CBlender_dlss() { description.CLS = 0; }

CBlender_dlss::~CBlender_dlss()
{
}

void CBlender_dlss::Compile(CBlender_Compile& C)
{
	IBlender::Compile(C);

	switch (C.iElement)
	{
	case 0: // motion vectors + depth
		C.r_Pass("stub_notransform_t", "dlss_mv", FALSE, FALSE, FALSE);
		C.r_dx10Texture("s_position", r2_RT_P);
		C.r_dx10Texture("s_dlss_obj", r2_RT_ssfx_motion_vectors);
		C.r_End();
		break;
	case 1: // their view
		C.r_Pass("stub_notransform_t", "dlss_mv_debug", FALSE, FALSE, FALSE);
		C.r_dx10Texture("s_dlss_mv", r2_RT_dlss_mv);
		C.r_dx10Texture("s_dlss_obj", r2_RT_ssfx_motion_vectors);
		C.r_End();
		break;
	case 2: // the output's copy
		C.r_Pass("stub_notransform_t", "render_scale", FALSE, FALSE, FALSE);
		C.r_dx10Texture("s_generic", r2_RT_dlss_out);
		C.r_dx10Sampler("smp_rtlinear");
		C.r_End();
		break;
	}
}

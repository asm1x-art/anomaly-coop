#include "stdafx.h"

#include "dlss.h"

// The DLSS SDK is not in the repository (NVIDIA's licence): tools/dlss/get_dlss_sdk.ps1 puts it in src/3rd party.
// Without it everything here says no_sdk and the game runs as before.
#if __has_include("../../3rd party/nvngx_dlss/include/nvsdk_ngx_helpers.h")
#define USE_DLSS 1
#include "../../3rd party/nvngx_dlss/include/nvsdk_ngx_helpers.h"
#include "../../3rd party/nvngx_dlss/include/nvsdk_ngx_helpers_d3d.h"
#pragma comment(lib, "nvsdk_ngx_d.lib")
#endif

namespace dlss
{
static status s_status = status::not_started;

const char* status_name(status s)
{
	switch (s)
	{
	case status::ok: return "ok";
	case status::not_started: return "not_started";
	case status::no_sdk: return "no_sdk";
	case status::headless: return "headless";
	case status::not_nvidia: return "not_nvidia";
	case status::msaa: return "msaa";
	case status::hdr10: return "hdr10";
	case status::no_dll: return "no_dll";
	case status::init_failed: return "init_failed";
	case status::old_driver: return "old_driver";
	case status::unsupported: return "unsupported";
	}
	return "unknown";
}

status get_status() { return s_status; }
bool available() { return s_status == status::ok; }

#ifdef USE_DLSS
// NGX wants a project id when the application has no id from NVIDIA: any GUID, the same for every build
static const char* project_id = "c8bfef75-1637-4d76-8686-a8367212b7fe";

static bool s_ngx = false; // NGX is initialised
static bool s_tried = false; // init ran since the start or shutdown(): its status stands
static NVSDK_NGX_Parameter* s_params = nullptr;
static NVSDK_NGX_Handle* s_handle = nullptr;
// A copy of the color input. From IX-Ray (DLSSWrapper::GetColorInput): on D3D11, DLSS reads its inputs through
// CUDA interop and sometimes saw another picture in the engine's render target than D3D11 did (a black output until
// the targets were made anew); a texture that is only ever written by a copy does not have that.
static ID3D11Texture2D* s_color = nullptr;

static NVSDK_NGX_PerfQuality_Value perf_value(u32 m)
{
	switch (m)
	{
	case mode_dlaa: return NVSDK_NGX_PerfQuality_Value_DLAA;
	case mode_quality: return NVSDK_NGX_PerfQuality_Value_MaxQuality;
	case mode_balanced: return NVSDK_NGX_PerfQuality_Value_Balanced;
	case mode_performance: return NVSDK_NGX_PerfQuality_Value_MaxPerf;
	default: return NVSDK_NGX_PerfQuality_Value_UltraPerformance;
	}
}

static void fail(status s, LPCSTR why, NVSDK_NGX_Result r = NVSDK_NGX_Result_Success)
{
	s_status = s;
	if (r != NVSDK_NGX_Result_Success)
		Msg("* DLSS: off, %s (%s, NGX 0x%08x)", status_name(s), why, u32(r));
	else
		Msg("* DLSS: off, %s (%s)", status_name(s), why);
}

static ID3D11Texture2D* color_copy(ID3D11Resource* src)
{
	ID3D11Texture2D* tex = nullptr;
	if (FAILED(src->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&tex)))
		return nullptr;
	D3D11_TEXTURE2D_DESC sd;
	tex->GetDesc(&sd);
	tex->Release();

	if (s_color)
	{
		D3D11_TEXTURE2D_DESC d;
		s_color->GetDesc(&d);
		if (d.Width != sd.Width || d.Height != sd.Height || d.Format != sd.Format)
			_RELEASE(s_color);
	}
	if (!s_color)
	{
		D3D11_TEXTURE2D_DESC d = sd;
		d.Usage = D3D11_USAGE_DEFAULT;
		d.BindFlags = D3D11_BIND_SHADER_RESOURCE;
		d.CPUAccessFlags = 0;
		d.MiscFlags = 0;
		if (FAILED(HW.pDevice->CreateTexture2D(&d, nullptr, &s_color)))
			return nullptr;
	}
	HW.pContext->CopyResource(s_color, src);
	return s_color;
}
#endif

void init(bool msaa, bool hdr10)
{
#ifndef USE_DLSS
	s_status = status::no_sdk;
	Msg("* DLSS: off, built without the DLSS SDK");
#else
	if (s_tried)
		return;
	s_tried = true;
	if (g_coop_headless)
		return fail(status::headless, "the co-op host draws nothing");
	if (HW.Caps.id_vendor != 0x10DE)
		return fail(status::not_nvidia, "not an NVIDIA video card");
	if (msaa)
		return fail(status::msaa, "MSAA is on (r3_msaa)");
	if (hdr10)
		return fail(status::hdr10, "HDR10 output is on");

	// nvngx_dlss.dll goes next to the exe
	wchar_t path[MAX_PATH];
	const DWORD n = GetModuleFileNameW(nullptr, path, MAX_PATH);
	if (n && n < MAX_PATH)
	{
		wchar_t* slash = wcsrchr(path, L'\\');
		if (slash)
			*(slash + 1) = 0;
		wcscat_s(path, L"nvngx_dlss.dll");
		if (GetFileAttributesW(path) == INVALID_FILE_ATTRIBUTES)
			return fail(status::no_dll, "nvngx_dlss.dll is not next to the exe");
	}

	// NGX writes its logs to the game's log folder
	wchar_t data_path[MAX_PATH] = L".";
	if (FS.path_exist("$logs$"))
		MultiByteToWideChar(CP_ACP, 0, FS.get_path("$logs$")->m_Path, -1, data_path, MAX_PATH);

	NVSDK_NGX_Result r = NVSDK_NGX_D3D11_Init_with_ProjectID(project_id, NVSDK_NGX_ENGINE_TYPE_CUSTOM, "anomaly-coop",
	                                                         data_path, HW.pDevice);
	if (NVSDK_NGX_FAILED(r))
		return fail(status::init_failed, "NGX did not start", r);
	s_ngx = true;

	r = NVSDK_NGX_D3D11_GetCapabilityParameters(&s_params);
	if (NVSDK_NGX_FAILED(r) || !s_params)
	{
		fail(status::init_failed, "no NGX parameters", r);
		shutdown();
		return;
	}

	int needs_driver = 0;
	if (NVSDK_NGX_SUCCEED(NVSDK_NGX_Parameter_GetI(s_params, NVSDK_NGX_Parameter_SuperSampling_NeedsUpdatedDriver,
	                                                &needs_driver)) && needs_driver)
	{
		unsigned int major = 0, minor = 0;
		NVSDK_NGX_Parameter_GetUI(s_params, NVSDK_NGX_Parameter_SuperSampling_MinDriverVersionMajor, &major);
		NVSDK_NGX_Parameter_GetUI(s_params, NVSDK_NGX_Parameter_SuperSampling_MinDriverVersionMinor, &minor);
		Msg("* DLSS: the driver must be %u.%u or newer", major, minor);
		fail(status::old_driver, "the video driver is too old");
		shutdown();
		return;
	}

	int ok = 0;
	r = NVSDK_NGX_Parameter_GetI(s_params, NVSDK_NGX_Parameter_SuperSampling_Available, &ok);
	if (NVSDK_NGX_FAILED(r) || !ok)
	{
		int init_result = 0;
		NVSDK_NGX_Parameter_GetI(s_params, NVSDK_NGX_Parameter_SuperSampling_FeatureInitResult, &init_result);
		Msg("* DLSS: not available on this card (NGX 0x%08x)", u32(init_result));
		fail(status::unsupported, "the video card has no DLSS");
		shutdown();
		return;
	}

	s_status = status::ok;
	Msg("* DLSS: available");
#endif
}

void shutdown()
{
#ifdef USE_DLSS
	s_tried = false;
	release_feature();
	_RELEASE(s_color);
	if (s_params)
	{
		NVSDK_NGX_D3D11_DestroyParameters(s_params);
		s_params = nullptr;
	}
	if (s_ngx)
	{
		NVSDK_NGX_D3D11_Shutdown1(HW.pDevice);
		s_ngx = false;
	}
#endif
}

bool optimal_size(u32 m, u32 display_w, u32 display_h, u32& render_w, u32& render_h)
{
#ifdef USE_DLSS
	if (!available() || m == mode_off)
		return false;
	if (m == mode_dlaa)
	{
		render_w = display_w;
		render_h = display_h;
		return true;
	}
	unsigned int w = 0, h = 0, max_w = 0, max_h = 0, min_w = 0, min_h = 0;
	float sharpness = 0.f;
	const NVSDK_NGX_Result r = NGX_DLSS_GET_OPTIMAL_SETTINGS(s_params, display_w, display_h, perf_value(m), &w, &h,
	                                                         &max_w, &max_h, &min_w, &min_h, &sharpness);
	if (NVSDK_NGX_FAILED(r) || !w || !h)
	{
		Msg("! DLSS: no render size for mode %u at %ux%u (NGX 0x%08x)", m, display_w, display_h, u32(r));
		return false;
	}
	render_w = w;
	render_h = h;
	return true;
#else
	return false;
#endif
}

bool create_feature(u32 m, u32 render_w, u32 render_h, u32 display_w, u32 display_h)
{
#ifdef USE_DLSS
	release_feature();
	if (!available() || m == mode_off)
		return false;

	NVSDK_NGX_DLSS_Create_Params p = {};
	p.Feature.InWidth = render_w;
	p.Feature.InHeight = render_h;
	p.Feature.InTargetWidth = display_w;
	p.Feature.InTargetHeight = display_h;
	p.Feature.InPerfQualityValue = perf_value(m);
	// the picture is tonemapped already (LDR: no HDR flag, no exposure); motion vectors at the render size, without the
	// jitter; depth 0 at the near plane
	p.InFeatureCreateFlags = NVSDK_NGX_DLSS_Feature_Flags_MVLowRes;

	const NVSDK_NGX_Result r = NGX_D3D11_CREATE_DLSS_EXT(HW.pContext, &s_handle, s_params, &p);
	if (NVSDK_NGX_FAILED(r) || !s_handle)
	{
		s_handle = nullptr;
		Msg("! DLSS: the feature was not made for %ux%u -> %ux%u (NGX 0x%08x)", render_w, render_h, display_w, display_h,
		    u32(r));
		return false;
	}
	Msg("* DLSS: %ux%u -> %ux%u, mode %u", render_w, render_h, display_w, display_h, m);
	return true;
#else
	return false;
#endif
}

void release_feature()
{
#ifdef USE_DLSS
	if (s_handle)
	{
		NVSDK_NGX_D3D11_ReleaseFeature(s_handle);
		s_handle = nullptr;
	}
#endif
}

bool feature_ready()
{
#ifdef USE_DLSS
	return s_handle != nullptr;
#else
	return false;
#endif
}

bool evaluate(ID3D11Resource* color, ID3D11Resource* mv, ID3D11Resource* depth, ID3D11Resource* out, u32 render_w,
              u32 render_h, float jitter_x, float jitter_y, bool reset, float frame_ms)
{
#ifdef USE_DLSS
	if (!s_handle)
		return false;
	ID3D11Texture2D* in = color_copy(color);
	if (!in)
		return false;

	NVSDK_NGX_D3D11_DLSS_Eval_Params e = {};
	e.Feature.pInColor = in;
	e.Feature.pInOutput = out;
	e.pInDepth = depth;
	e.pInMotionVectors = mv;
	e.InJitterOffsetX = jitter_x;
	e.InJitterOffsetY = jitter_y;
	e.InRenderSubrectDimensions.Width = render_w;
	e.InRenderSubrectDimensions.Height = render_h;
	e.InReset = reset ? 1 : 0;
	e.InMVScaleX = 1.f; // the motion vectors are in render pixels already
	e.InMVScaleY = 1.f;
	e.InFrameTimeDeltaInMsec = frame_ms;

	const NVSDK_NGX_Result r = NGX_D3D11_EVALUATE_DLSS_EXT(HW.pContext, s_handle, s_params, &e);
	if (NVSDK_NGX_FAILED(r))
	{
		static u32 reported = 0;
		if (reported++ < 5)
			Msg("! DLSS: evaluate failed (NGX 0x%08x)", u32(r));
		return false;
	}
	return true;
#else
	return false;
#endif
}
}

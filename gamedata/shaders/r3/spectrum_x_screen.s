-- Spectrum-X's device screen (ui_spectrum_x.script, the engine's 3D UI of hud items): as hud\p3d (the HUD's
-- projection, depth tested, no depth write, alpha blended), but the texture is tinted by the vertex colour (hud\p3d
-- drops it) and s_base is its only texture (the UI cuts atlas rects by stage 0's size)
function normal(shader, t_base, t_second, t_detail)
	shader:begin("spectrum_x_screen", "spectrum_x_screen")
		: fog(false)
		: zb(true, false)
		: blend(true, blend.srcalpha, blend.invsrcalpha)
		: dx10color_write_enable(true, true, true, false)
	shader:dx10texture("s_base", t_base)
	shader:dx10sampler("smp_base")
end

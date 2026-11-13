function normal(shader, t_base, t_second, t_detail)
	shader:begin	("deffer_model_hud_flat","models_selflight_det_DAR")
		: fog		(false)
		: zb		(true,false)
      	: blend   	(true,blend.srcalpha,blend.one)
      	: sorting	(1, true)

	shader:dx10texture	("s_base",	t_base)
	shader:dx10texture	("s_hud_rain","fx\\hud_rain")
	shader:dx10sampler	("smp_base")
end
#ifndef	dx10RainBlender_included
#define	dx10RainBlender_included

class CBlender_rain : public IBlender
{
public:
	virtual LPCSTR getComment() { return "INTERNAL: DX10 rain blender"; }
	virtual BOOL canBeDetailed() { return FALSE; }
	virtual BOOL canBeLMAPped() { return FALSE; }

	virtual void Compile(CBlender_Compile& C);
};

class CBlender_rain_msaa : public IBlender
{
public:
	CBlender_rain_msaa()
	{
		Name = 0;
		Definition = 0;
	}

	virtual LPCSTR getComment() { return "INTERNAL: DX10 MSAA rain blender"; }
	virtual BOOL canBeDetailed() { return FALSE; }
	virtual BOOL canBeLMAPped() { return FALSE; }

	virtual void Compile(CBlender_Compile& C);
	virtual void SetDefine(LPCSTR Name, LPCSTR Definition);

	LPCSTR Name;
	LPCSTR Definition;
};

// Co-op: ash settling on the ground during the Ash front (ash_ground.h): elements 0-3, the passes of draw_ash
class CBlender_ash : public IBlender
{
public:
	virtual LPCSTR getComment() { return "INTERNAL: ash on the ground"; }
	virtual BOOL canBeDetailed() { return FALSE; }
	virtual BOOL canBeLMAPped() { return FALSE; }

	virtual void Compile(CBlender_Compile& C);
};

#endif	//	dx10RainBlender_included

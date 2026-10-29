////////////////////////////////////////////////////////////////////////////
//	Module 		: UISecondTaskWnd.h
//	Created 	: 30.05.2008
//	Author		: Evgeniy Sokolov
//	Description : UI Secondary Task Wnd class
////////////////////////////////////////////////////////////////////////////

#ifndef UI_SECOND_TASK_WND_H_INCLUDED
#define UI_SECOND_TASK_WND_H_INCLUDED

#include "UIWindow.h"
#include "UIWndCallback.h"

#define PDA_TASK_XML	"pda_tasks.xml"

class CUIXml;
class CUIFrameWindow;
class CUIScrollView;
class CUIStatic;
class CUI3tButton;
class CUICheckButton;
class CUIFrameLineWnd;
class CGameTask;
class UIHint;

class UITaskListWnd : public CUIWindow, public CUIWndCallback
{
private:
	typedef CUIWindow inherited;

public:
	UITaskListWnd();
	virtual ~UITaskListWnd();

	void init_from_xml(CUIXml& xml, LPCSTR path);

	virtual bool OnMouseAction(float x, float y, EUIMessages mouse_action);
	virtual void OnMouseScroll(float iDirection);
	virtual void Show(bool status);
	virtual void OnFocusReceive();
	virtual void OnFocusLost();
	virtual void Update();
	virtual void SendMessage(CUIWindow* pWnd, s16 msg, void* pData);

	void UpdateList();

protected:
	void xr_stdcall OnBtnClose(CUIWindow* w, void* d);
	bool xr_stdcall SortingLessFunction(CUIWindow* left, CUIWindow* right);

	//			void	UpdateCounter		();
public:
	UIHint* hint_wnd;

private: // m_
	CUIFrameWindow* m_background;
	CUIScrollView* m_list;

	CUIStatic* m_caption;
	//	CUIStatic*			m_counter;
	CUI3tButton* m_bt_close;

	//	u32					m_activ_task_count;
	float m_orig_h;
}; // class UITaskListWnd

// -------------------------------------------------------------------------------------------------

class UITaskListWndItem : public CUIWindow
{
private:
	typedef CUIWindow inherited;

public:
	UITaskListWndItem();
	virtual ~UITaskListWndItem();

	bool init_task(CGameTask* task, UITaskListWnd* parent);
	// a group of tasks (the script's _G.CGameTask__group: the shelter's "Убежище"): listed together, its title on the
	// first one, the rest indented under it; folded, the title is all there is of it (a click on the title folds it
	// or unfolds it)
	void set_group(const shared_str& group, u32 group_priority, bool header, bool folded, CUIXml& xml);
	IC u32 get_priority_task() const;
	bool sorts_before(const UITaskListWndItem& other) const;

	virtual void OnFocusReceive();
	virtual void OnFocusLost();
	virtual void Update();
	virtual void SendMessage(CUIWindow* pWnd, s16 msg, void* pData);
	virtual bool OnMouseAction(float x, float y, EUIMessages mouse_action);

private:
	void hide_hint();
	void update_view();
	void update_visible_map_spot();

public:
	bool show_hint_can;
	bool show_hint;

private: // m_
	CGameTask* m_task;
	CUI3tButton* m_name;
	//	CUICheckButton*	m_bt_view;
	CUIStatic* m_st_story;
	CUI3tButton* m_bt_focus;

	shared_str m_group;
	u32 m_group_priority;
	bool m_group_header;
	float m_group_title_h; // the group's title's height on the item that carries it

	enum
	{
		stt_activ = 0,
		stt_unread,
		stt_read,
		stt_count
	};

	u32 m_color_states[stt_count];
}; // class UITaskListWndItem

#endif // UI_SECOND_TASK_WND_H_INCLUDED

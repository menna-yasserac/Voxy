"""
AT-SPI2 Screen Accessibility Controller for Voxy (Ubuntu Linux).
Searches active window first, filters visible elements, and supports both
direct AT-SPI doAction and bounding-box center click fallback.
"""

import os
import shutil
import subprocess

try:
    import pyatspi
    HAS_PYATSPI = True
except ImportError:
    pyatspi = None
    HAS_PYATSPI = False


class ATSPIController:
    INTERACTIVE_ROLES = {
        "push button",
        "toggle button",
        "check box",
        "radio button",
        "menu item",
        "menu",
        "link",
        "page tab",
        "text",
        "entry",
        "password text",
        "combo box",
        "list item",
        "icon",
    }

    def __init__(self):
        if not HAS_PYATSPI:
            raise ImportError(
                "python3-pyatspi is not installed. Run: sudo apt install python3-pyatspi"
            )
        self.desktop = pyatspi.Registry.getDesktop(0)

    def _is_showing(self, node):
        try:
            state_set = node.getState()
            return state_set.contains(pyatspi.STATE_SHOWING) or state_set.contains(pyatspi.STATE_VISIBLE)
        except Exception:
            return True

    def _is_active_window(self, node):
        try:
            state_set = node.getState()
            return state_set.contains(pyatspi.STATE_ACTIVE)
        except Exception:
            return False

    def _iter_nodes(self, root, max_depth=12, depth=0):
        if root is None or depth > max_depth:
            return
        yield root
        try:
            count = root.childCount
            for i in range(count):
                child = root.getChildAtIndex(i)
                yield from self._iter_nodes(child, max_depth=max_depth, depth=depth + 1)
        except Exception:
            pass

    def _get_ordered_roots(self):
        """Returns active windows first, then all other desktop applications."""
        active_roots = []
        other_roots = []
        for app in self.desktop:
            if app is None:
                continue
            try:
                for i in range(app.childCount):
                    win = app.getChildAtIndex(i)
                    if win and self._is_active_window(win):
                        active_roots.append(win)
                    elif win:
                        other_roots.append(win)
            except Exception:
                other_roots.append(app)
        return active_roots + other_roots

    def list_elements(self):
        elements = []
        seen = set()
        try:
            for root in self._get_ordered_roots():
                for node in self._iter_nodes(root, max_depth=10):
                    try:
                        if not self._is_showing(node):
                            continue
                        name = (node.name or "").strip()
                        role = node.getRoleName()
                        if name and role in self.INTERACTIVE_ROLES:
                            key = (role, name)
                            if key not in seen:
                                seen.add(key)
                                elements.append({
                                    "name": name,
                                    "role": role,
                                })
                    except Exception:
                        continue
            return {
                "success": True,
                "message": f"Found {len(elements)} visible UI elements.",
                "elements": elements[:100],
            }
        except Exception as error:
            return {"success": False, "message": str(error), "elements": []}

    def _click_by_extents(self, node):
        """Gets the screen bounding box of the element and clicks its center."""
        try:
            comp = node.queryComponent()
            if not comp:
                return False
            ext = comp.getExtents(pyatspi.DESKTOP_COORDS)
            if ext.width <= 0 or ext.height <= 0:
                return False
            cx = int(ext.x + ext.width / 2)
            cy = int(ext.y + ext.height / 2)

            if shutil.which("xdotool") and os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland":
                res = subprocess.run(
                    ["xdotool", "mousemove", str(cx), str(cy), "click", "1"],
                    capture_output=True, timeout=5
                )
                return res.returncode == 0

            if shutil.which("ydotool"):
                subprocess.run(["ydotool", "mousemove", "--absolute", "-x", str(cx), "-y", str(cy)], timeout=3)
                res = subprocess.run(["ydotool", "click", "0xC0"], timeout=3)
                return res.returncode == 0
        except Exception:
            pass
        return False

    def click(self, target_name):
        target_cf = str(target_name or "").strip().casefold()
        cleaned_cf = target_cf
        for noise in ("button", "btn", "زر", "زرار", "أيقونة", "icon"):
            cleaned_cf = cleaned_cf.replace(noise, "").strip()
        if not cleaned_cf:
            cleaned_cf = target_cf

        if not cleaned_cf:
            return {"success": False, "message": "Target element name is empty."}

        exact_showing = None
        partial_showing = None
        fallback_match = None

        for root in self._get_ordered_roots():
            for node in self._iter_nodes(root, max_depth=12):
                try:
                    name = (node.name or "").strip()
                    if not name:
                        continue
                    name_cf = name.casefold()
                    showing = self._is_showing(node)

                    if name_cf in (target_cf, cleaned_cf):
                        if showing:
                            exact_showing = node
                            break
                        elif fallback_match is None:
                            fallback_match = node
                    elif (cleaned_cf in name_cf or name_cf in cleaned_cf) and len(cleaned_cf) >= 2:
                        if showing and partial_showing is None:
                            partial_showing = node
                        elif fallback_match is None:
                            fallback_match = node
                except Exception:
                    continue
            if exact_showing is not None:
                break

        chosen = exact_showing or partial_showing or fallback_match
        if chosen is None:
            return {"success": False, "message": f"UI element '{target_name}' was not found on screen."}

        # 1. المحاولة الأولى: AT-SPI doAction المباشر
        try:
            action_iface = chosen.queryAction()
            if action_iface and action_iface.nActions > 0:
                action_iface.doAction(0)
                return {"success": True, "message": f"Clicked '{chosen.name}'."}
        except Exception:
            pass

        # 2. المحاولة الثانية: حساب إحداثيات العنصر على الشاشة والضغط في منتصفه
        if self._click_by_extents(chosen):
            return {"success": True, "message": f"Clicked '{chosen.name}' at its screen coordinates."}

        # 3. المحاولة الثالثة: التركيز والضغط على Enter
        try:
            comp = chosen.queryComponent()
            if comp:
                comp.grabFocus()
                pyatspi.Registry.generateKeyboardEvent(36, None, pyatspi.KEY_PRESSRELEASE)
                return {"success": True, "message": f"Activated '{chosen.name}'."}
        except Exception:
            pass

        return {"success": False, "message": f"Element '{chosen.name}' was found but could not be clicked."}

    def type_text(self, target_name, text):
        target_cf = str(target_name or "").strip().casefold()
        if not target_cf:
            return {"success": False, "message": "Target field name is empty."}

        for root in self._get_ordered_roots():
            for node in self._iter_nodes(root, max_depth=12):
                try:
                    name = (node.name or "").strip()
                    if target_cf in name.casefold() and self._is_showing(node):
                        edit_iface = node.queryEditableText()
                        if edit_iface:
                            edit_iface.setTextContents(str(text))
                            return {"success": True, "message": f"Typed into '{name}'."}
                except Exception:
                    continue

        return {"success": False, "message": f"Editable field '{target_name}' was not found."}
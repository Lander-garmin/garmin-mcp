import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// Today's coach messages stored by the background refresh:
// {"morning" => text, "evening" => text, "week" => text}.
function todayMessages() {
    var face = Application.Storage.getValue("face");
    if (!(face instanceof Dictionary) || !faceDate().equals(face["date"])) {
        return {};
    }
    var msgs = face["msgs"];
    return msgs instanceof Dictionary ? msgs : {};
}

// START on the widget: pick a message.
class CoachDelegate extends WatchUi.BehaviorDelegate {
    function initialize() {
        BehaviorDelegate.initialize();
    }

    function onSelect() {
        var msgs = todayMessages();
        if (msgs.size() == 0) {
            return true;   // nothing to read yet; stay on the widget
        }
        WatchUi.pushView(new MessagesMenu(msgs), new MessagesMenuDelegate(msgs), WatchUi.SLIDE_UP);
        return true;
    }
}

class MessagesMenu extends WatchUi.Menu2 {
    function initialize(msgs) {
        Menu2.initialize({:title => "Trainer"});
        if (msgs.hasKey("morning")) {
            addItem(new WatchUi.MenuItem("Buenos dias", null, "morning", {}));
        }
        if (msgs.hasKey("evening")) {
            addItem(new WatchUi.MenuItem("Resumen del dia", null, "evening", {}));
        }
        if (msgs.hasKey("week")) {
            addItem(new WatchUi.MenuItem("Plan semana", null, "week", {}));
        }
    }
}

class MessagesMenuDelegate extends WatchUi.Menu2InputDelegate {
    var msgs;

    function initialize(m) {
        Menu2InputDelegate.initialize();
        msgs = m;
    }

    function onSelect(item) {
        var id = item.getId();
        var title = id.equals("morning") ? "BUENOS DIAS" : (id.equals("evening") ? "RESUMEN DEL DIA" : "PLAN SEMANA");
        var pager = new TextPager(title, msgs[id].toString());
        WatchUi.pushView(pager, new TextPagerDelegate(pager), WatchUi.SLIDE_LEFT);
    }

    function onBack() {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
    }
}

// Black-on-white reader: one row per line of the message, thin dividers
// between rows, long rows wrapped to two lines. UP/DOWN change page, BACK returns.
class TextPager extends WatchUi.View {
    const TOP = 0.25;
    const BOTTOM = 0.85;
    const PAD = 5;   // space above and below each row; the divider sits in between
    var title;
    var text;
    var pagesList = null;   // [[row, row, ...], ...]; row = {:lines, :font, :h}
    var page = 0;

    function initialize(t, body) {
        View.initialize();
        title = t;
        text = body;
    }

    function pages() {
        return pagesList == null ? 1 : pagesList.size();
    }

    function turn(delta) {
        var p = page + delta;
        if (p >= 0 && p < pages()) {
            page = p;
            WatchUi.requestUpdate();
        }
    }

    function onUpdate(dc) {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_WHITE);
        dc.clear();
        try {
            if (pagesList == null) {
                pagesList = layout(dc, (w * 0.80).toNumber(), ((BOTTOM - TOP) * h).toNumber());
            }
            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.14, Graphics.FONT_XTINY, title, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
            dc.setPenWidth(2);
            dc.drawLine(cx - 30, h * 0.21, cx + 30, h * 0.21);
            dc.setPenWidth(1);

            var rows = pagesList[page];
            var y = (h * TOP).toNumber();
            for (var i = 0; i < rows.size(); i += 1) {
                var r = rows[i];
                if (i > 0) {
                    dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
                    dc.drawLine(cx - 20, y, cx + 20, y);
                }
                dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
                var lines = r[:lines];
                var fh = dc.getFontHeight(r[:font]);
                for (var j = 0; j < lines.size(); j += 1) {
                    dc.drawText(cx, y + PAD + fh * j + fh / 2, r[:font], lines[j],
                        Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
                }
                y += r[:h];
            }
            drawDots(dc, cx, (h * 0.91).toNumber());
        } catch (e) {
            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h / 2, Graphics.FONT_SMALL, title, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        }
    }

    function drawDots(dc, cx, y) {
        var n = pages();
        if (n < 2) {
            return;
        }
        var gap = 10;
        var x0 = cx - (n - 1) * gap / 2;
        for (var i = 0; i < n; i += 1) {
            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            if (i == page) {
                dc.fillCircle(x0 + i * gap, y, 3);
            } else {
                dc.drawCircle(x0 + i * gap, y, 3);
            }
        }
    }

    // Rows from the message lines; each row takes one line or, if long, two.
    function layout(dc, maxW, areaH) {
        var items = splitLines(text);
        var fh = dc.getFontHeight(Graphics.FONT_XTINY);
        var pagesOut = [];
        var rows = [];
        var used = 0;
        for (var i = 0; i < items.size(); i += 1) {
            var item = items[i];
            var row;
            if (dc.getTextWidthInPixels(item, Graphics.FONT_XTINY) <= maxW) {
                row = {:lines => [item], :font => Graphics.FONT_XTINY, :h => fh + 2 * PAD};
            } else {
                var two = wrapTwo(dc, item, maxW);
                row = {:lines => two, :font => Graphics.FONT_XTINY, :h => fh * two.size() + 2 * PAD};
            }
            if (used + row[:h] > areaH && rows.size() > 0) {
                pagesOut.add(rows);
                rows = [];
                used = 0;
            }
            rows.add(row);
            used += row[:h];
        }
        if (rows.size() > 0 || pagesOut.size() == 0) {
            pagesOut.add(rows);
        }
        return pagesOut;
    }

    // Non-empty lines of the message (split on newline character code 10).
    function splitLines(t) {
        var out = [];
        var cur = "";
        var chars = t.toCharArray();
        for (var i = 0; i < chars.size(); i += 1) {
            var code = chars[i].toNumber();
            if (code == 10) {
                if (cur.length() > 0) {
                    out.add(cur);
                }
                cur = "";
            } else if (code != 13) {
                cur = cur + chars[i].toString();
            }
        }
        if (cur.length() > 0) {
            out.add(cur);
        }
        return out;
    }

    // Up to two lines; the second is shortened with "." if it still does not fit.
    function wrapTwo(dc, item, maxW) {
        var first = "";
        var rest = item;
        while (rest.length() > 0) {
            var sp = rest.find(" ");
            var word = sp == null ? rest : rest.substring(0, sp);
            var cand = first.length() == 0 ? word : first + " " + word;
            if (first.length() > 0 && dc.getTextWidthInPixels(cand, Graphics.FONT_XTINY) > maxW) {
                break;
            }
            first = cand;
            rest = sp == null ? "" : rest.substring(sp + 1, rest.length());
        }
        if (rest.length() == 0) {
            return [first];
        }
        while (rest.length() > 1 && dc.getTextWidthInPixels(rest, Graphics.FONT_XTINY) > maxW) {
            rest = rest.substring(0, rest.length() - 2) + ".";
        }
        return [first, rest];
    }
}

class TextPagerDelegate extends WatchUi.BehaviorDelegate {
    var pager;

    function initialize(p) {
        BehaviorDelegate.initialize();
        pager = p;
    }

    function onNextPage() {
        pager.turn(1);
        return true;
    }

    function onPreviousPage() {
        pager.turn(-1);
        return true;
    }

    function onBack() {
        WatchUi.popView(WatchUi.SLIDE_RIGHT);
        return true;
    }
}

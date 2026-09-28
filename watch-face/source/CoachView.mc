import Toybox.Application;
import Toybox.Communications;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.SensorHistory;
import Toybox.System;
import Toybox.WatchUi;

class CoachView extends WatchUi.View {
    var status = "";   // "" | "Actualizando..." | "Sin conexion (code)"

    function initialize() {
        View.initialize();
    }

    // Fresh data every time the widget is opened (needs the phone).
    function onShow() {
        status = "Actualizando...";
        try {
            Communications.makeWebRequest(
                Secrets.SERVER_URL + "/watch/face",
                {"k" => Secrets.WATCH_KEY, "date" => faceDate()},
                {
                    :method => Communications.HTTP_REQUEST_METHOD_GET,
                    :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
                },
                method(:onFace)
            );
        } catch (e) {
        }
    }

    function onFace(code, data) {
        if (code == 200) {
            storeFace(data);
            scheduleRefresh();
            status = "";
        } else {
            // -104: no phone link, -300: timeout, 401/404/5xx: server side.
            status = "Sin conexion (" + code.toString() + ")";
        }
        WatchUi.requestUpdate();
    }

    function onUpdate(dc) {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_WHITE);
        dc.clear();
        try {
            draw(dc, cx, h);
        } catch (e) {
            txt(dc, cx, h / 2, Graphics.FONT_SMALL, "Trainer");
        }
    }

    function draw(dc, cx, h) {
        var top = "HOY";
        var bb = bodyBattery();
        if (bb != null) {
            top = top + "     BB " + bb.format("%d");
        }
        txt(dc, cx, h * 0.18, Graphics.FONT_XTINY, top);

        var face = Application.Storage.getValue("face");
        var today = (face instanceof Dictionary) && faceDate().equals(face["date"]);
        var items = today ? face["items"] : null;
        if (!(items instanceof Array) || items.size() == 0) {
            txt(dc, cx, h * 0.38, Graphics.FONT_MEDIUM, today ? "Descanso" : "Sin datos");
        } else {
            txt(dc, cx, h * 0.36, Graphics.FONT_SMALL, shortLabel(items[0].toString()));
            if (items.size() > 1) {
                txt(dc, cx, h * 0.48, Graphics.FONT_XTINY, shortLabel(items[1].toString()));
            }
        }

        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(cx - 50, h * 0.58, cx + 50, h * 0.58);

        if (today && face.hasKey("note") && face["note"] instanceof String) {
            note(dc, cx, h * 0.63, face["note"]);
        }
        if (status.equals("") && todayMessages().size() > 0) {
            txt(dc, cx, h * 0.87, Graphics.FONT_XTINY, "START mensajes");
        }
        if (!status.equals("")) {
            txt(dc, cx, h * 0.88, Graphics.FONT_XTINY, status);
        }
    }

    function bodyBattery() {
        try {
            if ((Toybox has :SensorHistory) && (SensorHistory has :getBodyBatteryHistory)) {
                var it = SensorHistory.getBodyBatteryHistory({:period => 1});
                if (it != null) {
                    var s = it.next();
                    if (s != null && s.data != null) {
                        return s.data.toNumber();
                    }
                }
            }
        } catch (e) {
        }
        return null;
    }

    // "17:30 Gym Push 70 min" -> "17:30 Gym Push"
    function shortLabel(t) {
        var out = "";
        var words = 0;
        var rest = t;
        while (words < 3 && rest.length() > 0) {
            var sp = rest.find(" ");
            var word = sp == null ? rest : rest.substring(0, sp);
            out = words == 0 ? word : out + " " + word;
            words += 1;
            rest = sp == null ? "" : rest.substring(sp + 1, rest.length());
        }
        return out;
    }

    // The coach note on up to two lines that fit the round screen.
    function note(dc, x, y, t) {
        var line1 = "";
        var rest = t;
        while (rest.length() > 0) {
            var sp = rest.find(" ");
            var word = sp == null ? rest : rest.substring(0, sp);
            var cand = line1.length() == 0 ? word : line1 + " " + word;
            if (cand.length() > 20 && line1.length() > 0) {
                break;
            }
            line1 = cand;
            rest = sp == null ? "" : rest.substring(sp + 1, rest.length());
        }
        if (rest.length() > 18) {
            rest = rest.substring(0, 17) + ".";
        }
        if (rest.length() == 0) {
            txt(dc, x, y, Graphics.FONT_XTINY, line1);
        } else {
            txt(dc, x, y - 1, Graphics.FONT_XTINY, line1);
            txt(dc, x, y + 17, Graphics.FONT_XTINY, rest);
        }
    }

    function txt(dc, x, y, font, t) {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
        dc.drawText(x, y, font, t, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}

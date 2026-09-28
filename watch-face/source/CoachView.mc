import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.SensorHistory;
import Toybox.System;
import Toybox.Time;
import Toybox.Time.Gregorian;
import Toybox.WatchUi;

class CoachView extends WatchUi.WatchFace {
    const DAYS = ["", "DOM", "LUN", "MAR", "MIE", "JUE", "VIE", "SAB"];

    function initialize() {
        WatchFace.initialize();
    }

    function onUpdate(dc) {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_WHITE);
        dc.clear();

        var clock = System.getClockTime();
        var info = Gregorian.info(Time.now(), Time.FORMAT_SHORT);
        var hour = clock.hour;
        if (!System.getDeviceSettings().is24Hour) {
            hour = hour % 12;
            if (hour == 0) {
                hour = 12;
            }
        }

        // Date and Body Battery on one line.
        var top = DAYS[info.day_of_week] + " " + info.day.format("%d");
        var bb = bodyBattery();
        if (bb != null) {
            top = top + "   BB " + bb.format("%d");
        }
        txt(dc, cx, h * 0.16, Graphics.FONT_XTINY, top);

        txt(dc, cx, h * 0.33, Graphics.FONT_NUMBER_HOT, hour.format("%d") + ":" + clock.min.format("%02d"));

        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
        dc.drawLine(cx - 50, h * 0.50, cx + 50, h * 0.50);

        var face = Application.Storage.getValue("face");
        var today = face instanceof Dictionary && faceDate().equals(face["date"]);
        var items = today ? face["items"] : null;
        if (items == null || items.size() == 0) {
            txt(dc, cx, h * 0.59, Graphics.FONT_SMALL, today ? "Descanso" : "--");
        } else {
            txt(dc, cx, h * 0.59, Graphics.FONT_SMALL, shortLabel(items[0]));
            if (items.size() > 1) {
                txt(dc, cx, h * 0.68, Graphics.FONT_XTINY, shortLabel(items[1]));
            }
        }
        if (today && face.hasKey("note")) {
            note(dc, cx, h * 0.79, face["note"]);
        }
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

    function bodyBattery() {
        if (!(Toybox has :SensorHistory) || !(SensorHistory has :getBodyBatteryHistory)) {
            return null;
        }
        var it = SensorHistory.getBodyBatteryHistory({:period => 1});
        if (it == null) {
            return null;
        }
        var s = it.next();
        return (s != null && s.data != null) ? s.data.toNumber() : null;
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

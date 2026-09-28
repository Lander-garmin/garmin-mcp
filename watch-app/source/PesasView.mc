import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

function fmtKg(w) {
    if (w == null) {
        return "";
    }
    if (w == w.toNumber()) {
        return w.toNumber().format("%d") + " kg";
    }
    return w.format("%.1f") + " kg";
}

function fmtTime(sec) {
    var m = sec / 60;
    var s = sec % 60;
    return m.format("%d") + ":" + s.format("%02d");
}

// "8 x 80 kg", "12 reps", "45 s"
function targetText(m) {
    var e = m.current();
    if (e.hasKey("sec")) {
        return e["sec"].format("%d") + " s" + (m.curW == null ? "" : " x " + fmtKg(m.curW));
    }
    if (m.curW == null) {
        return m.curR.format("%d") + " reps";
    }
    return m.curR.format("%d") + " x " + fmtKg(m.curW);
}

function setText(s) {
    var r = s["r"].format("%d");
    return s.hasKey("w") ? r + " x " + fmtKg(s["w"]) : r + " reps";
}

function volumeKg(m) {
    var v = 0.0;
    for (var i = 0; i < m.sets.size(); i += 1) {
        var s = m.sets[i];
        if (s.hasKey("w")) {
            v += s["w"] * s["r"];
        }
    }
    return v.toNumber();
}

class MainView extends WatchUi.View {
    function initialize() {
        View.initialize();
    }

    function onUpdate(dc) {
        var m = getModel();
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        var st = m.state;
        if (st == ST_LOADING || st == ST_READY) {
            title(dc, cx, h * 0.38, "GYM");
            text(dc, cx, h * 0.56, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, m.state == ST_LOADING ? "Buscando entreno de hoy..." : m.message);
        } else if (st == ST_NOPLAN || st == ST_ERROR) {
            title(dc, cx, h * 0.24, "GYM");
            text(dc, cx, h * 0.42, Graphics.FONT_XTINY, Graphics.COLOR_WHITE, m.message);
            text(dc, cx, h * 0.62, Graphics.FONT_XTINY, Graphics.COLOR_GREEN, "START  sesion libre");
            text(dc, cx, h * 0.74, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, "BACK  salir");
        } else if (st == ST_WAIT) {
            drawWait(dc, m, cx, h);
        } else if (st == ST_SET) {
            drawSet(dc, m, cx, w, h);
        } else if (st == ST_REST) {
            drawRest(dc, m, cx, w, h);
        } else if (st == ST_DONE) {
            drawDone(dc, m, cx, h, "START  guardar");
        } else if (st == ST_SAVED) {
            drawDone(dc, m, cx, h, m.sendStatus);
            text(dc, cx, h * 0.86, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, "BACK  salir");
        }
    }

    function drawWait(dc, m, cx, h) {
        var e = m.current();
        if (m.freeSession) {
            title(dc, cx, h * 0.24, "LIBRE");
            text(dc, cx, h * 0.40, Graphics.FONT_XTINY, Graphics.COLOR_WHITE, "LAP al acabar cada serie");
            text(dc, cx, h * 0.50, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, "UP/DOWN reps en descanso");
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            dc.fillRoundedRectangle(cx - 62, h * 0.66, 124, 28, 12);
            text(dc, cx, h * 0.66 + 14, Graphics.FONT_XTINY, Graphics.COLOR_BLACK, "START empezar");
            return;
        }
        text(dc, cx, h * 0.20, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, m.shortName());
        text(dc, cx, h * 0.33, nameFont(e["n"]), Graphics.COLOR_WHITE, e["n"]);
        text(dc, cx, h * 0.47, Graphics.FONT_SMALL, Graphics.COLOR_YELLOW, targetText(m));
        text(dc, cx, h * 0.58, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY,
            e["s"].format("%d") + " series  -  " + m.ex.size().format("%d") + " ejercicios");
        if (!m.message.equals("")) {
            text(dc, cx, h * 0.66, Graphics.FONT_XTINY, Graphics.COLOR_ORANGE, m.message);
        }
        dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
        dc.fillRoundedRectangle(cx - 62, h * 0.71, 124, 28, 12);
        text(dc, cx, h * 0.71 + 14, Graphics.FONT_XTINY, Graphics.COLOR_BLACK, "START empezar");
    }

    function drawSet(dc, m, cx, w, h) {
        var e = m.current();
        header(dc, m, cx, h);
        text(dc, cx, h * 0.28, nameFont(e["n"]), Graphics.COLOR_WHITE, e["n"]);
        if (m.freeSession) {
            text(dc, cx, h * 0.55, Graphics.FONT_MEDIUM, Graphics.COLOR_YELLOW, "Serie " + m.setNo.format("%d"));
            text(dc, cx, h * 0.79, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, "LAP al acabar");
            return;
        }
        text(dc, cx, h * 0.40, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY,
            "Serie " + m.setNo.format("%d") + " de " + e["s"].format("%d") + "  |  Ej " + (m.exIdx + 1).format("%d") + "/" + m.ex.size().format("%d"));
        text(dc, cx, h * 0.55, Graphics.FONT_MEDIUM, Graphics.COLOR_YELLOW, targetText(m));
        if (e.hasKey("note")) {
            text(dc, cx, h * 0.68, Graphics.FONT_XTINY, Graphics.COLOR_ORANGE, e["note"]);
        }
        text(dc, cx, h * 0.79, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, m.curW == null ? "UP/DOWN reps" : "UP/DOWN peso");
        progressDots(dc, cx, h * 0.89, m.setNo, e["s"]);
    }

    function drawRest(dc, m, cx, w, h) {
        // Countdown ring around the edge.
        if (m.restTotal > 0) {
            dc.setPenWidth(8);
            dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawCircle(cx, h / 2, cx - 5);
            var frac = m.restLeft.toFloat() / m.restTotal;
            if (frac > 0) {
                dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
                dc.drawArc(cx, h / 2, cx - 5, Graphics.ARC_CLOCKWISE, 90, 90 - (360 * frac).toNumber());
            }
            dc.setPenWidth(1);
        }
        header(dc, m, cx, h);
        text(dc, cx, h * 0.27, Graphics.FONT_XTINY, Graphics.COLOR_BLUE, "DESCANSO");
        var t = m.restTotal > 0 ? fmtTime(m.restLeft) : "+" + fmtTime(m.restCountUp);
        text(dc, cx, h * 0.43, Graphics.FONT_NUMBER_MEDIUM, Graphics.COLOR_WHITE, t);
        if (m.sets.size() > 0) {
            text(dc, cx, h * 0.59, Graphics.FONT_XTINY, Graphics.COLOR_YELLOW, "Hecho: " + setText(m.sets[m.sets.size() - 1]));
            text(dc, cx, h * 0.68, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, "UP/DOWN reps");
        }
        text(dc, cx, h * 0.78, Graphics.FONT_XTINY, Graphics.COLOR_WHITE, nextText(m));
    }

    // "Sigue: serie 2/4" or, when the exercise changes, "Sigue: Lateral Raise".
    function nextText(m) {
        var e = m.current();
        if (m.setNo > 1) {
            return "Sigue: serie " + m.setNo.format("%d") + "/" + e["s"].format("%d");
        }
        var n = e["n"];
        return "Sigue: " + (n.length() > 13 ? n.substring(0, 13) : n);
    }

    function drawDone(dc, m, cx, h, footer) {
        title(dc, cx, h * 0.22, m.state == ST_SAVED ? "GUARDADO" : "TERMINADO");
        text(dc, cx, h * 0.40, Graphics.FONT_SMALL, Graphics.COLOR_WHITE, m.sets.size().format("%d") + " series");
        text(dc, cx, h * 0.53, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, fmtTime(m.elapsed()) + "  -  " + volumeKg(m).format("%d") + " kg");
        text(dc, cx, h * 0.70, Graphics.FONT_XTINY, Graphics.COLOR_GREEN, footer);
    }

    function header(dc, m, cx, h) {
        var hr = m.heartRate();
        var s = fmtTime(m.elapsed()) + (hr == null ? "" : "   " + hr.format("%d") + " ppm");
        text(dc, cx, h * 0.14, Graphics.FONT_XTINY, Graphics.COLOR_LT_GRAY, s);
    }

    function progressDots(dc, cx, y, current, total) {
        if (total > 8) {
            return;
        }
        var gap = 12;
        var x0 = cx - (total - 1) * gap / 2;
        for (var i = 1; i <= total; i += 1) {
            dc.setColor(i < current ? Graphics.COLOR_GREEN : (i == current ? Graphics.COLOR_YELLOW : Graphics.COLOR_DK_GRAY), Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(x0 + (i - 1) * gap, y, 4);
        }
    }

    function nameFont(n) {
        return n.length() > 14 ? Graphics.FONT_XTINY : Graphics.FONT_SMALL;
    }

    function title(dc, x, y, t) {
        text(dc, x, y, Graphics.FONT_MEDIUM, Graphics.COLOR_ORANGE, t);
    }

    function text(dc, x, y, font, color, t) {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(x, y, font, t, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}

// START = select, BACK/LAP = back, UP = previous page, DOWN = next page,
// hold UP = menu (Forerunner 55 buttons).
class MainDelegate extends WatchUi.BehaviorDelegate {
    function initialize() {
        BehaviorDelegate.initialize();
    }

    function onSelect() {
        var m = getModel();
        var st = m.state;
        if (st == ST_NOPLAN || st == ST_ERROR) {
            m.startFreeSession();
        } else if (st == ST_WAIT) {
            m.startSession();
        } else if (st == ST_SET) {
            m.completeSet();
        } else if (st == ST_REST) {
            m.endRest();
        } else if (st == ST_DONE) {
            m.save();
        }
        return true;
    }

    function onBack() {
        var m = getModel();
        var st = m.state;
        if (st == ST_SET) {
            m.completeSet();
            return true;
        }
        if (st == ST_REST) {
            m.endRest();
            return true;
        }
        if (st == ST_DONE) {
            return true;
        }
        if (st == ST_WAIT && m.plan != null && !m.freeSession) {
            // Back to "Hoy: Realizar / Ver", like a scheduled run.
            m.state = ST_READY;
            WatchUi.pushView(new PlanMenu(), new PlanMenuDelegate(), WatchUi.SLIDE_RIGHT);
            return true;
        }
        // Not recording: BACK leaves the app.
        return false;
    }

    function onNextPage() {
        getModel().adjust(-1);
        return true;
    }

    function onPreviousPage() {
        getModel().adjust(1);
        return true;
    }

    function onMenu() {
        var m = getModel();
        if (m.session != null || m.state == ST_DONE) {
            WatchUi.pushView(new SessionMenu(), new SessionMenuDelegate(), WatchUi.SLIDE_UP);
        }
        return true;
    }
}

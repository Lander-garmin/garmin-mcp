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

function targetText(m) {
    var e = m.current();
    var reps = e.hasKey("sec") ? e["sec"].format("%d") + " s" : m.curR.format("%d");
    if (m.curW == null) {
        return reps + " reps";
    }
    return reps + " x " + fmtKg(m.curW);
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
            center(dc, cx, h * 0.40, Graphics.FONT_MEDIUM, "Pesas");
            center(dc, cx, h * 0.58, Graphics.FONT_XTINY, m.message);
        } else if (st == ST_NOPLAN || st == ST_ERROR) {
            center(dc, cx, h * 0.28, Graphics.FONT_SMALL, "Pesas");
            center(dc, cx, h * 0.45, Graphics.FONT_XTINY, m.message);
            center(dc, cx, h * 0.62, Graphics.FONT_XTINY, "START: sesion libre");
            center(dc, cx, h * 0.74, Graphics.FONT_XTINY, "BACK: salir");
        } else if (st == ST_WAIT) {
            center(dc, cx, h * 0.22, Graphics.FONT_XTINY, m.shortName());
            center(dc, cx, h * 0.40, Graphics.FONT_SMALL, m.current()["n"]);
            center(dc, cx, h * 0.56, Graphics.FONT_XTINY, m.current()["s"].format("%d") + " series - " + targetText(m));
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            center(dc, cx, h * 0.74, Graphics.FONT_SMALL, "Pulsa START");
        } else if (st == ST_SET) {
            drawSet(dc, m, cx, h);
        } else if (st == ST_REST) {
            drawRest(dc, m, cx, h);
        } else if (st == ST_DONE) {
            center(dc, cx, h * 0.30, Graphics.FONT_SMALL, "Entreno");
            center(dc, cx, h * 0.44, Graphics.FONT_SMALL, "completado");
            center(dc, cx, h * 0.58, Graphics.FONT_XTINY, m.sets.size().format("%d") + " series - " + fmtTime(m.elapsed()));
            dc.setColor(Graphics.COLOR_GREEN, Graphics.COLOR_TRANSPARENT);
            center(dc, cx, h * 0.74, Graphics.FONT_XTINY, "START: guardar");
        } else if (st == ST_SAVED) {
            center(dc, cx, h * 0.36, Graphics.FONT_SMALL, "Guardado");
            center(dc, cx, h * 0.52, Graphics.FONT_XTINY, m.sendStatus);
            center(dc, cx, h * 0.70, Graphics.FONT_XTINY, "BACK: salir");
        }
    }

    function drawSet(dc, m, cx, h) {
        var e = m.current();
        center(dc, cx, h * 0.14, Graphics.FONT_XTINY, fmtTime(m.elapsed()) + hrText(m));
        center(dc, cx, h * 0.30, Graphics.FONT_SMALL, e["n"]);
        center(dc, cx, h * 0.45, Graphics.FONT_XTINY,
            "Serie " + m.setNo.format("%d") + "/" + e["s"].format("%d") + "   Ej " + (m.exIdx + 1).format("%d") + "/" + m.ex.size().format("%d"));
        dc.setColor(Graphics.COLOR_YELLOW, Graphics.COLOR_TRANSPARENT);
        center(dc, cx, h * 0.62, Graphics.FONT_MEDIUM, targetText(m));
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        if (e.hasKey("note")) {
            center(dc, cx, h * 0.77, Graphics.FONT_XTINY, e["note"]);
        }
        center(dc, cx, h * 0.88, Graphics.FONT_XTINY, "LAP: serie hecha");
    }

    function drawRest(dc, m, cx, h) {
        center(dc, cx, h * 0.14, Graphics.FONT_XTINY, fmtTime(m.elapsed()) + hrText(m));
        center(dc, cx, h * 0.27, Graphics.FONT_SMALL, "Descanso");
        dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        var t = m.restTotal > 0 ? fmtTime(m.restLeft) : "+" + fmtTime(m.restCountUp);
        center(dc, cx, h * 0.46, Graphics.FONT_NUMBER_MEDIUM, t);
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        if (m.sets.size() > 0) {
            var last = m.sets[m.sets.size() - 1];
            var done = last["r"].format("%d") + (last.hasKey("w") ? " x " + fmtKg(last["w"]) : " reps");
            center(dc, cx, h * 0.66, Graphics.FONT_XTINY, "Hecho: " + done + " (UP/DOWN)");
        }
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        center(dc, cx, h * 0.80, Graphics.FONT_XTINY, "Sigue: " + m.current()["n"]);
    }

    function hrText(m) {
        var hr = m.heartRate();
        return hr == null ? "" : "   " + hr.format("%d") + " ppm";
    }

    function center(dc, x, y, font, text) {
        dc.drawText(x, y, font, text, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
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

import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

// Minimal black-on-white screens, like Garmin's own workout pages.
// Buttons: START = do / confirm, UP/DOWN = change a number, BACK = pause.

function fmtKg(w) {
    if (w == w.toNumber()) {
        return w.toNumber().format("%d");
    }
    return w.format("%.1f");
}

function seriesText(n) {
    return n.format("%d") + (n == 1 ? " serie" : " series");
}

function fmtTime(sec) {
    return (sec / 60).format("%d") + ":" + (sec % 60).format("%02d");
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
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_WHITE);
        dc.clear();

        var st = m.state;
        if (st == ST_LOADING) {
            txt(dc, cx, h * 0.50, Graphics.FONT_SMALL, "Gym");
        } else if (st == ST_START) {
            drawStart(dc, m, cx, h);
        } else if (st == ST_SET) {
            drawSet(dc, m, cx, h);
        } else if (st == ST_LOG) {
            drawLog(dc, m, cx, w, h);
        } else if (st == ST_REST) {
            drawRest(dc, m, cx, h);
        } else if (st == ST_TIMER) {
            drawTimer(dc, m, cx, h);
        } else if (st == ST_DONE) {
            small(dc, cx, h * 0.28, "ENTRENO TERMINADO");
            txt(dc, cx, h * 0.47, Graphics.FONT_MEDIUM, seriesText(m.sets.size()));
            small(dc, cx, h * 0.62, fmtTime(m.elapsed()));
            small(dc, cx, h * 0.80, "START guardar");
        } else if (st == ST_SAVED) {
            small(dc, cx, h * 0.28, "GUARDADO");
            txt(dc, cx, h * 0.47, Graphics.FONT_MEDIUM, seriesText(m.sets.size()));
            small(dc, cx, h * 0.62, m.sendStatus);
            small(dc, cx, h * 0.80, "BACK salir");
        }
    }

    function drawStart(dc, m, cx, h) {
        small(dc, cx, h * 0.24, m.free ? "SIN ENTRENO HOY" : "HOY");
        txt(dc, cx, h * 0.42, Graphics.FONT_MEDIUM, m.title());
        if (!m.free) {
            small(dc, cx, h * 0.57, m.exerciseCount().format("%d") + " ejercicios");
        }
        small(dc, cx, h * 0.75, "START empezar");
        if (!m.free) {
            small(dc, cx, h * 0.86, "DOWN ver");
        }
    }

    // "SERIE 2 DE 3", "CALENTAMIENTO", "SUPERSERIE 2 DE 3"
    function setHeader(m) {
        var b = m.block();
        if (m.isWarmup()) {
            return "CALENTAMIENTO";
        }
        if (m.isSuperset()) {
            return "SUPERSERIE " + m.round().format("%d") + " DE " + b["s"].format("%d");
        }
        return "SERIE " + m.round().format("%d") + " DE " + b["s"].format("%d");
    }

    // "12 reps", "60 s", "500 m"
    function targetText(e) {
        if (e.hasKey("sec")) {
            return e["sec"].format("%d") + " s";
        }
        if (e.hasKey("m")) {
            return e["m"].format("%d") + " m";
        }
        if (e.hasKey("r")) {
            return e["r"].format("%d") + " reps";
        }
        return "";
    }

    function drawSet(dc, m, cx, h) {
        var e = m.current();
        if (m.free) {
            small(dc, cx, h * 0.26, "SERIE " + m.round().format("%d"));
            txt(dc, cx, h * 0.50, Graphics.FONT_MEDIUM, "Entrenando");
            small(dc, cx, h * 0.85, "START al terminar");
            return;
        }
        small(dc, cx, h * 0.20, setHeader(m));
        name(dc, cx, h * 0.35, e["n"]);
        if (m.targetW != null) {
            txt(dc, cx, h * 0.55, Graphics.FONT_LARGE, fmtKg(m.targetW) + " kg");
            txt(dc, cx, h * 0.70, Graphics.FONT_SMALL, targetText(e));
        } else {
            txt(dc, cx, h * 0.57, Graphics.FONT_LARGE, targetText(e));
        }
        small(dc, cx, h * 0.85, m.isTimed() ? "START empezar" : "START al terminar");
    }

    // Timed set running (sled push 60 s): big countdown, closes by itself.
    function drawTimer(dc, m, cx, h) {
        var total = m.current()["sec"];
        if (total > 0 && m.timerLeft > 0) {
            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            dc.setPenWidth(5);
            var deg = (360 * m.timerLeft / total).toNumber();
            dc.drawArc(cx, h / 2, cx - 4, Graphics.ARC_CLOCKWISE, 90, 90 - deg);
            dc.setPenWidth(1);
        }
        name(dc, cx, h * 0.24, m.current()["n"]);
        txt(dc, cx, h * 0.48, Graphics.FONT_NUMBER_HOT, fmtTime(m.timerLeft));
        if (m.targetW != null) {
            small(dc, cx, h * 0.68, fmtKg(m.targetW) + " kg");
        }
        small(dc, cx, h * 0.86, "START parar");
    }

    // Like setting an alarm: the highlighted box is the one UP/DOWN changes.
    function drawLog(dc, m, cx, w, h) {
        small(dc, cx, h * 0.20, m.isWarmup() ? "CALENT. HECHO" : "SERIE HECHA");
        var top = (h * 0.32).toNumber();
        var bh = (h * 0.34).toNumber();
        if (m.hasRepsField() && m.hasWeightField()) {
            box(dc, cx - 82, top, 78, bh, "REPS", m.logR.format("%d"), m.logField == 0);
            box(dc, cx + 4, top, 78, bh, "KG", fmtKg(m.logW), m.logField == 1);
        } else if (m.hasRepsField()) {
            box(dc, cx - 50, top, 100, bh, "REPS", m.logR.format("%d"), true);
        } else {
            box(dc, cx - 50, top, 100, bh, "KG", fmtKg(m.logW), true);
        }
        small(dc, cx, h * 0.76, "UP/DOWN cambiar");
        small(dc, cx, h * 0.86, "START ok");
    }

    function drawRest(dc, m, cx, h) {
        if (m.restTotal > 0 && m.restLeft > 0) {
            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            dc.setPenWidth(5);
            var deg = (360 * m.restLeft / m.restTotal).toNumber();
            dc.drawArc(cx, h / 2, cx - 4, Graphics.ARC_CLOCKWISE, 90, 90 - deg);
            dc.setPenWidth(1);
        }
        small(dc, cx, h * 0.24, "DESCANSO");
        txt(dc, cx, h * 0.45, Graphics.FONT_NUMBER_HOT, fmtTime(m.restLeft));
        var next = m.free ? "Serie " + m.round().format("%d") : m.current()["n"];
        small(dc, cx, h * 0.66, m.free ? "SIGUE" : setHeader(m));
        name(dc, cx, h * 0.75, next);
        small(dc, cx, h * 0.88, "START saltar");
    }

    function box(dc, x, y, bw, bh, label, value, active) {
        if (active) {
            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            dc.fillRoundedRectangle(x, y, bw, bh, 8);
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        } else {
            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            dc.setPenWidth(2);
            dc.drawRoundedRectangle(x, y, bw, bh, 8);
            dc.setPenWidth(1);
        }
        var c = x + bw / 2;
        dc.drawText(c, y + bh * 0.22, Graphics.FONT_XTINY, label, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        dc.drawText(c, y + bh * 0.62, Graphics.FONT_NUMBER_MILD, value, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }

    // Exercise names: one line if short, two smaller lines if long.
    function name(dc, x, y, n) {
        if (n.length() <= 15) {
            txt(dc, x, y, Graphics.FONT_SMALL, n);
            return;
        }
        var cut = n.length() / 2;
        var best = null;
        for (var i = 0; i < n.length(); i += 1) {
            if (n.substring(i, i + 1).equals(" ")) {
                if (best == null || (i - cut).abs() < (best - cut).abs()) {
                    best = i;
                }
            }
        }
        if (best == null) {
            txt(dc, x, y, Graphics.FONT_XTINY, n);
            return;
        }
        txt(dc, x, y - 9, Graphics.FONT_XTINY, n.substring(0, best));
        txt(dc, x, y + 9, Graphics.FONT_XTINY, n.substring(best + 1, n.length()));
    }

    function small(dc, x, y, t) {
        txt(dc, x, y, Graphics.FONT_XTINY, t);
    }

    function txt(dc, x, y, font, t) {
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
        dc.drawText(x, y, font, t, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}

class MainDelegate extends WatchUi.BehaviorDelegate {
    function initialize() {
        BehaviorDelegate.initialize();
    }

    // START: begin / set done / confirm / skip rest / save
    function onSelect() {
        var m = getModel();
        var st = m.state;
        if (st == ST_START) {
            m.begin();
        } else if (st == ST_SET) {
            m.setDone();
        } else if (st == ST_LOG) {
            m.logNext();
        } else if (st == ST_REST) {
            m.endRest();
        } else if (st == ST_TIMER) {
            m.stopTimed();
        } else if (st == ST_DONE) {
            WatchUi.pushView(new FeelMenu(), new FeelMenuDelegate(), WatchUi.SLIDE_UP);
        }
        return true;
    }

    // BACK: pause while training; otherwise leave the app.
    function onBack() {
        var m = getModel();
        if (m.session != null) {
            WatchUi.pushView(new PauseMenu(), new PauseMenuDelegate(), WatchUi.SLIDE_UP);
            return true;
        }
        return false;
    }

    function onNextPage() {
        var m = getModel();
        if (m.state == ST_START && !m.free) {
            WatchUi.pushView(new PlanDetailMenu(), new PlanDetailDelegate(), WatchUi.SLIDE_UP);
        } else {
            m.adjust(-1);
        }
        return true;
    }

    function onPreviousPage() {
        getModel().adjust(1);
        return true;
    }

    function onMenu() {
        return onBack();
    }
}

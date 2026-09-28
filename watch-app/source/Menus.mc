import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

// "Entreno de hoy": the same choice the watch offers for a scheduled run.
class PlanMenu extends WatchUi.Menu2 {
    function initialize() {
        Menu2.initialize({:title => "Entreno de hoy"});
        var m = getModel();
        addItem(new WatchUi.MenuItem("Realizar entreno", m.shortName(), :realizar, {}));
        addItem(new WatchUi.MenuItem("Ver entreno", m.ex.size().format("%d") + " ejercicios", :ver, {}));
        addItem(new WatchUi.MenuItem("Sesion libre", "Sin plan", :libre, {}));
    }
}

class PlanMenuDelegate extends WatchUi.Menu2InputDelegate {
    function initialize() {
        Menu2InputDelegate.initialize();
    }

    function onSelect(item) {
        var id = item.getId();
        var m = getModel();
        if (id == :realizar) {
            WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
            m.chooseRealizar();
        } else if (id == :ver) {
            WatchUi.pushView(new PlanDetailMenu(), new PlanDetailDelegate(), WatchUi.SLIDE_LEFT);
        } else if (id == :libre) {
            WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
            m.startFreeSession();
        }
    }

    function onBack() {
        WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
        System.exit();
    }
}

// "Ver entreno": one line per exercise, e.g. "4 x 8 - 80 kg - 2:00".
class PlanDetailMenu extends WatchUi.Menu2 {
    function initialize() {
        var m = getModel();
        Menu2.initialize({:title => m.shortName()});
        for (var i = 0; i < m.ex.size(); i += 1) {
            var e = m.ex[i];
            var reps = e.hasKey("sec") ? e["sec"].format("%d") + "s" : (e.hasKey("r") ? e["r"].format("%d") : "-");
            var sub = e["s"].format("%d") + " x " + reps;
            if (e.hasKey("w")) {
                sub = sub + " - " + fmtKg(e["w"].toFloat());
            }
            if (e["rest"] > 0) {
                sub = sub + " - " + fmtTime(e["rest"]);
            }
            addItem(new WatchUi.MenuItem(e["n"], sub, i, {}));
        }
    }
}

class PlanDetailDelegate extends WatchUi.Menu2InputDelegate {
    function initialize() {
        Menu2InputDelegate.initialize();
    }

    function onSelect(item) {
    }

    function onBack() {
        WatchUi.popView(WatchUi.SLIDE_RIGHT);
    }
}

// Hold UP during the session.
class SessionMenu extends WatchUi.Menu2 {
    function initialize() {
        Menu2.initialize({:title => "Sesion"});
        addItem(new WatchUi.MenuItem("Continuar", null, :cont, {}));
        addItem(new WatchUi.MenuItem("Siguiente ejercicio", null, :skip, {}));
        addItem(new WatchUi.MenuItem("Terminar y guardar", null, :save, {}));
        addItem(new WatchUi.MenuItem("Descartar", null, :discard, {}));
    }
}

class SessionMenuDelegate extends WatchUi.Menu2InputDelegate {
    function initialize() {
        Menu2InputDelegate.initialize();
    }

    function onSelect(item) {
        var id = item.getId();
        var m = getModel();
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        if (id == :skip) {
            m.skipExercise();
        } else if (id == :save) {
            m.save();
        } else if (id == :discard) {
            m.discard();
        }
    }
}

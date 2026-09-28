import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

// BACK during the session: same choices as Garmin's own activities.
class PauseMenu extends WatchUi.Menu2 {
    function initialize() {
        Menu2.initialize({:title => "Pausa"});
        addItem(new WatchUi.MenuItem("Seguir", null, :resume, {}));
        addItem(new WatchUi.MenuItem("Guardar", null, :save, {}));
        if (!getModel().free) {
            addItem(new WatchUi.MenuItem("Saltar ejercicio", null, :skip, {}));
        }
        addItem(new WatchUi.MenuItem("Descartar", null, :discard, {}));
    }
}

class PauseMenuDelegate extends WatchUi.Menu2InputDelegate {
    function initialize() {
        Menu2InputDelegate.initialize();
    }

    function onSelect(item) {
        var id = item.getId();
        var m = getModel();
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        if (id == :save) {
            m.save();
        } else if (id == :skip) {
            m.skipExercise();
        } else if (id == :discard) {
            WatchUi.pushView(new ConfirmDiscard(), new ConfirmDiscardDelegate(), WatchUi.SLIDE_UP);
        }
    }

    function onBack() {
        WatchUi.popView(WatchUi.SLIDE_DOWN);   // BACK again = keep training
    }
}

class ConfirmDiscard extends WatchUi.Menu2 {
    function initialize() {
        Menu2.initialize({:title => "Descartar?"});
        addItem(new WatchUi.MenuItem("No", null, :no, {}));
        addItem(new WatchUi.MenuItem("Si, descartar", null, :yes, {}));
    }
}

class ConfirmDiscardDelegate extends WatchUi.Menu2InputDelegate {
    function initialize() {
        Menu2InputDelegate.initialize();
    }

    function onSelect(item) {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        if (item.getId() == :yes) {
            getModel().discard();
        }
    }
}

// DOWN on the start screen: today's exercises, e.g. "4 x 8   80 kg".
class PlanDetailMenu extends WatchUi.Menu2 {
    function initialize() {
        var m = getModel();
        Menu2.initialize({:title => m.title()});
        for (var i = 0; i < m.ex.size(); i += 1) {
            var e = m.ex[i];
            var reps = e.hasKey("sec") ? e["sec"].format("%d") + " s" : (e.hasKey("r") ? e["r"].format("%d") : "-");
            var sub = e["s"].format("%d") + " x " + reps;
            if (e.hasKey("w")) {
                sub = sub + "   " + fmtKg(e["w"].toFloat()) + " kg";
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
        WatchUi.popView(WatchUi.SLIDE_DOWN);
    }
}

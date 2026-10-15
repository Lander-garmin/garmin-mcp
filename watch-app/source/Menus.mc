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
            addItem(new WatchUi.MenuItem("Saltar bloque", null, :skip, {}));
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
            WatchUi.pushView(new FeelMenu(), new FeelMenuDelegate(), WatchUi.SLIDE_UP);
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

// DOWN on the start screen: today's exercises, e.g. "3 x 12   80 kg".
class PlanDetailMenu extends WatchUi.Menu2 {
    function initialize() {
        var m = getModel();
        Menu2.initialize({:title => m.title()});
        var id = 0;
        for (var b = 0; b < m.blocks.size(); b += 1) {
            var blk = m.blocks[b];
            var xs = blk["x"];
            for (var i = 0; i < xs.size(); i += 1) {
                var e = xs[i];
                var target = e.hasKey("sec") ? e["sec"].format("%d") + " s"
                    : (e.hasKey("m") ? e["m"].format("%d") + " m"
                    : (e.hasKey("r") ? e["r"].format("%d") : "-"));
                var sub = blk["s"].format("%d") + " x " + target;
                if (e.hasKey("w")) {
                    sub = sub + "  " + fmtKg(e["w"].toFloat()) + " kg";
                }
                if (blk.hasKey("wu")) {
                    sub = "Calent. " + sub;
                } else if (xs.size() > 1) {
                    sub = "SS " + sub;
                }
                addItem(new WatchUi.MenuItem(e["n"], sub, id, {}));
                id += 1;
            }
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

// Before saving: how did it feel? Same scale Garmin asks after its own activities
// (stored as directWorkoutFeel 0/25/50/75/100).
class FeelMenu extends WatchUi.Menu2 {
    function initialize() {
        Menu2.initialize({:title => "Sensacion"});
        addItem(new WatchUi.MenuItem("Muy bien", null, 100, {}));
        addItem(new WatchUi.MenuItem("Bien", null, 75, {}));
        addItem(new WatchUi.MenuItem("Normal", null, 50, {}));
        addItem(new WatchUi.MenuItem("Mal", null, 25, {}));
        addItem(new WatchUi.MenuItem("Muy mal", null, 0, {}));
        addItem(new WatchUi.MenuItem("Guardar sin valorar", null, -1, {}));
        setFocus(2);
    }
}

class FeelMenuDelegate extends WatchUi.Menu2InputDelegate {
    function initialize() {
        Menu2InputDelegate.initialize();
    }

    function onSelect(item) {
        var feel = item.getId();
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        if (feel < 0) {
            getModel().saveRated(null, null);
        } else {
            WatchUi.pushView(new RpeMenu(), new RpeMenuDelegate(feel), WatchUi.SLIDE_UP);
        }
    }

    function onBack() {
        WatchUi.popView(WatchUi.SLIDE_DOWN);   // back to the session, nothing saved
    }
}

// Then: perceived effort 1-10 (directWorkoutRpe, stored x10 by the server).
class RpeMenu extends WatchUi.Menu2 {
    function initialize() {
        Menu2.initialize({:title => "Esfuerzo"});
        var labels = ["Muy facil", "Muy facil", "Facil", "Facil", "Moderado", "Moderado",
            "Duro", "Duro", "Muy duro", "Maximo"];
        for (var i = 1; i <= 10; i += 1) {
            addItem(new WatchUi.MenuItem(i.format("%d"), labels[i - 1], i, {}));
        }
        setFocus(6);
    }
}

class RpeMenuDelegate extends WatchUi.Menu2InputDelegate {
    var feel;

    function initialize(f) {
        Menu2InputDelegate.initialize();
        feel = f;
    }

    function onSelect(item) {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        getModel().saveRated(feel, item.getId());
    }

    function onBack() {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        getModel().saveRated(feel, null);   // feel only
    }
}

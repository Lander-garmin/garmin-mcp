import Toybox.Application;
import Toybox.Background;
import Toybox.Lang;
import Toybox.Time;
import Toybox.WatchUi;

// "Gym": guided strength sessions for watches without a native strength
// profile (Forerunner 55). A background service downloads today's workout from
// the Sync EU server whenever the watch is connected to the phone, so it is
// ready at the gym without the phone. The app walks set by set, records a
// Strength activity and sends the performed sets back to the server.
(:background)
class PesasApp extends Application.AppBase {
    var model = null;

    function initialize() {
        AppBase.initialize();
    }

    function getInitialView() {
        model = new PesasModel();
        // Refresh today's plan every hour in the background while connected.
        Background.registerForTemporalEvent(new Time.Duration(60 * 60));
        model.resendPending();
        model.fetchPlan();
        return [new MainView(), new MainDelegate()];
    }

    function getServiceDelegate() {
        return [new GymService()];
    }

    // Plan downloaded by the background service: keep it for offline use.
    function onBackgroundData(data) {
        if (data instanceof Dictionary && data["ok"] == true && data.hasKey("date")) {
            Application.Storage.setValue("plan", data);
        }
    }

    function onStop(state) {
        if (model != null) {
            model.onAppStop();
        }
    }
}

function getModel() {
    return Application.getApp().model;
}

import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

// "Pesas": guided strength sessions for watches without a native strength
// profile (Forerunner 55). Gets today's workout from the Sync EU server,
// walks through sets / reps / kg / rest, records a Strength activity and sends
// the performed sets back so the server can attach them in Garmin Connect.
class PesasApp extends Application.AppBase {
    var model;

    function initialize() {
        AppBase.initialize();
        model = new PesasModel();
    }

    function onStart(state) {
        model.resendPending();
        model.fetchPlan();
    }

    function onStop(state) {
        model.onAppStop();
    }

    function getInitialView() {
        return [new MainView(), new MainDelegate()];
    }
}

function getModel() {
    return Application.getApp().model;
}

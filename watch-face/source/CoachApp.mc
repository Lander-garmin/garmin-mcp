import Toybox.Application;
import Toybox.Background;
import Toybox.Lang;
import Toybox.Time;
import Toybox.WatchUi;

// "Coach" widget (UP/DOWN from the watch face): today's sessions from the
// Garmin calendar, Body Battery and a one-line note from the Claude coach.
// Refreshes when opened and every 30 minutes in the background via the phone.
// Every risky call is guarded so the widget never shows the Connect IQ error.
(:background)
class CoachApp extends Application.AppBase {
    function initialize() {
        AppBase.initialize();
    }

    function getInitialView() {
        try {
            Background.registerForTemporalEvent(new Time.Duration(30 * 60));
        } catch (e) {
            // Background refresh is a nice-to-have; the widget also fetches on open.
        }
        return [new CoachView()];
    }

    function getServiceDelegate() {
        return [new CoachService()];
    }

    function onBackgroundData(data) {
        storeFace(data);
        WatchUi.requestUpdate();
    }
}

(:background)
function storeFace(data) {
    if (data instanceof Dictionary && data["ok"] == true && data["date"] instanceof String) {
        Application.Storage.setValue("face", data);
    }
}

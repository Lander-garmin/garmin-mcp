import Toybox.Application;
import Toybox.Background;
import Toybox.Lang;
import Toybox.Time;
import Toybox.WatchUi;

// "Coach" watch face: time, today's sessions from the Garmin calendar, Body
// Battery and a one-line note written by the Claude coach every morning.
// A background service refreshes the data every 30 minutes via the phone.
(:background)
class CoachApp extends Application.AppBase {
    function initialize() {
        AppBase.initialize();
    }

    function getInitialView() {
        var cached = Application.Storage.getValue("face");
        if (cached instanceof Dictionary && faceDate().equals(cached["date"])) {
            Background.registerForTemporalEvent(new Time.Duration(30 * 60));
        } else {
            // Nothing for today yet: ask as soon as the system allows.
            Background.registerForTemporalEvent(Time.now());
        }
        return [new CoachView()];
    }

    function getServiceDelegate() {
        return [new CoachService()];
    }

    function onBackgroundData(data) {
        if (data instanceof Dictionary && data["ok"] == true) {
            Application.Storage.setValue("face", data);
        }
        Background.registerForTemporalEvent(new Time.Duration(30 * 60));
        WatchUi.requestUpdate();
    }
}

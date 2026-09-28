import Toybox.Application;
import Toybox.Background;
import Toybox.Lang;
import Toybox.Time;
import Toybox.WatchUi;

// "Trainer" widget (UP/DOWN from the watch face): today's sessions from the
// Garmin calendar, Body Battery and a one-line note from the Claude coach.
// Refreshes when opened and every 30 minutes in the background via the phone.
// Every risky call is guarded so the widget never shows the Connect IQ error.
(:background)
class CoachApp extends Application.AppBase {
    function initialize() {
        AppBase.initialize();
    }

    function getInitialView() {
        scheduleRefresh();
        return [new CoachView(), new CoachDelegate()];
    }

    function getServiceDelegate() {
        return [new CoachService()];
    }

    function onBackgroundData(data) {
        storeFace(data);
        scheduleRefresh();
        WatchUi.requestUpdate();
    }
}

// Every 5 minutes (Garmin's minimum) until today's data is on the watch, so it
// arrives a few minutes after the phone connects; then every 30 minutes.
function scheduleRefresh() {
    var face = Application.Storage.getValue("face");
    var haveToday = (face instanceof Dictionary) && faceDate().equals(face["date"]);
    try {
        Background.registerForTemporalEvent(new Time.Duration((haveToday ? 30 : 5) * 60));
    } catch (e) {
        // Background refresh is a nice-to-have; the widget also fetches on open.
    }
}

(:background)
function storeFace(data) {
    if (data instanceof Dictionary && data["ok"] == true && data["date"] instanceof String) {
        Application.Storage.setValue("face", data);
    }
}

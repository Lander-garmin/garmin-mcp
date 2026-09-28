import Toybox.Application;
import Toybox.Background;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.System;
import Toybox.Time;
import Toybox.Time.Gregorian;

// Runs in the background (hourly). Fetches today's plan through the phone and
// hands it to the app, which stores it for when there is no phone at the gym.
(:background)
class GymService extends System.ServiceDelegate {
    function initialize() {
        ServiceDelegate.initialize();
    }

    function onTemporalEvent() {
        Communications.makeWebRequest(
            Secrets.SERVER_URL + "/watch/today",
            {"k" => Secrets.WATCH_KEY, "date" => localDate()},
            {
                :method => Communications.HTTP_REQUEST_METHOD_GET,
                :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
            },
            method(:onPlan)
        );
    }

    function onPlan(code, data) {
        Background.exit(code == 200 ? data : null);
    }
}

(:background)
function localDate() {
    var d = Gregorian.info(Time.now(), Time.FORMAT_SHORT);
    return d.year.format("%04d") + "-" + d.month.format("%02d") + "-" + d.day.format("%02d");
}

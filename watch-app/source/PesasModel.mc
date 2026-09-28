import Toybox.Activity;
import Toybox.ActivityRecording;
import Toybox.Application;
import Toybox.Attention;
import Toybox.Communications;
import Toybox.FitContributor;
import Toybox.Lang;
import Toybox.Sensor;
import Toybox.System;
import Toybox.Time;
import Toybox.Timer;
import Toybox.WatchUi;

// Screens
const ST_LOADING = 0;   // looking for today's plan
const ST_START = 1;     // plan (or free session) ready: START to begin
const ST_SET = 2;       // doing a set: START when finished
const ST_LOG = 3;       // note reps and kg of the set just done
const ST_REST = 4;      // rest countdown
const ST_DONE = 5;      // all sets done: START to save
const ST_SAVED = 6;     // saved

const WEIGHT_STEP = 2.5;
const REST_BETWEEN_EXERCISES = 90;

class PesasModel {
    var state = ST_LOADING;
    var plan = null;
    var ex = [];
    var free = false;
    var offline = false;
    var exIdx = 0;
    var setNo = 1;
    var targetW = null;       // kg for the next set (null = bodyweight)
    var logField = 0;         // 0 = reps, 1 = kg
    var logR = 0;
    var logW = null;
    var restTotal = 0;
    var restLeft = 0;
    var sets = [];
    var session = null;
    var fieldEx = null;
    var fieldReps = null;
    var fieldKg = null;
    var startMs = 0;
    var startEpoch = 0;
    var setStart = 0;
    var finalElapsed = 0;
    var timer = null;
    var sendStatus = "";

    function initialize() {
    }

    // ------------------------------------------------------------------
    // Plan
    // ------------------------------------------------------------------

    function fetchPlan() {
        state = ST_LOADING;
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
        if (code == 200 && data instanceof Dictionary && data["ok"] == true) {
            Application.Storage.setValue("plan", data);
            usePlan(data);
        } else {
            // No phone: use the plan the background service saved earlier today.
            offline = true;
            var cached = Application.Storage.getValue("plan");
            if (cached instanceof Dictionary && localDate().equals(cached["date"])) {
                usePlan(cached);
            } else {
                usePlan(null);
            }
        }
        WatchUi.requestUpdate();
    }

    function usePlan(data) {
        if (data != null && !data.hasKey("none") && data["ex"] != null && data["ex"].size() > 0) {
            plan = data;
            ex = data["ex"];
            free = false;
        } else {
            plan = null;
            free = true;
            ex = [{"n" => "Ejercicio", "c" => "UNKNOWN", "e" => "UNKNOWN", "s" => 999, "rest" => 0}];
        }
        exIdx = 0;
        setNo = 1;
        targetW = current().hasKey("w") ? current()["w"].toFloat() : null;
        state = ST_START;
    }

    function current() {
        return ex[exIdx];
    }

    function targetReps() {
        var e = current();
        if (e.hasKey("r")) {
            return e["r"];
        }
        if (e.hasKey("sec")) {
            return e["sec"];
        }
        return 0;
    }

    function isTimed() {
        return current().hasKey("sec");
    }

    // "Plan X 30/09 Gym Push 70 min" -> "Push"
    function title() {
        if (plan == null) {
            return "Sesion libre";
        }
        var n = plan["name"];
        var i = n.find("Gym ");
        var skip = 4;
        if (i == null) {
            i = n.find("Pesas ");
            skip = 6;
        }
        if (i == null) {
            return n.length() > 16 ? n.substring(0, 16) : n;
        }
        var rest = n.substring(i + skip, n.length());
        var sp = rest.find(" ");
        return sp == null ? rest : rest.substring(0, sp);
    }

    function activityName() {
        return plan == null ? "Gym" : "Gym " + title();
    }

    // ------------------------------------------------------------------
    // Session
    // ------------------------------------------------------------------

    function begin() {
        Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE]);
        var name = activityName();
        session = ActivityRecording.createSession({
            :name => name.length() > 15 ? name.substring(0, 15) : name,
            :sport => Activity.SPORT_TRAINING,
            :subSport => Activity.SUB_SPORT_STRENGTH_TRAINING
        });
        fieldEx = session.createField("ejercicio", 0, FitContributor.DATA_TYPE_STRING,
            {:mesgType => FitContributor.MESG_TYPE_LAP, :count => 24});
        fieldReps = session.createField("repeticiones", 1, FitContributor.DATA_TYPE_UINT16,
            {:mesgType => FitContributor.MESG_TYPE_LAP, :units => "reps"});
        fieldKg = session.createField("peso", 2, FitContributor.DATA_TYPE_FLOAT,
            {:mesgType => FitContributor.MESG_TYPE_LAP, :units => "kg"});
        session.start();
        startMs = System.getTimer();
        startEpoch = Time.now().value();
        setStart = startEpoch;
        timer = new Timer.Timer();
        timer.start(method(:onTick), 1000, true);
        state = ST_SET;
        buzz(1);
        WatchUi.requestUpdate();
    }

    function elapsed() {
        if (session == null) {
            return finalElapsed;
        }
        return (System.getTimer() - startMs) / 1000;
    }

    // START on the set screen: the set is done, now note reps and kg.
    function setDone() {
        logR = targetReps();
        logW = targetW;
        if (free) {
            logW = 0.0;
            if (sets.size() > 0) {
                var last = sets[sets.size() - 1];
                logR = last["r"];
                logW = last.hasKey("w") ? last["w"] : 0.0;
            }
        }
        logField = 0;
        state = ST_LOG;
        WatchUi.requestUpdate();
    }

    function hasWeightField() {
        return logW != null;
    }

    // UP / DOWN on the log screen change the highlighted field.
    function adjust(delta) {
        if (state != ST_LOG) {
            return;
        }
        if (logField == 0) {
            logR = logR + delta;
            if (logR < 0) {
                logR = 0;
            }
        } else {
            logW = logW + WEIGHT_STEP * delta;
            if (logW < 0) {
                logW = 0.0;
            }
        }
        WatchUi.requestUpdate();
    }

    // START on the log screen: next field, or confirm the set.
    function logNext() {
        if (logField == 0 && hasWeightField()) {
            logField = 1;
            WatchUi.requestUpdate();
            return;
        }
        confirmSet();
    }

    function confirmSet() {
        var now = Time.now().value();
        var e = current();
        var s = {"c" => e["c"], "e" => e["e"], "r" => logR, "t" => setStart, "d" => now - setStart};
        if (logW != null && !(free && logW == 0.0)) {
            s["w"] = logW;
        }
        sets.add(s);
        writeLap(e["n"], s);
        if (logW != null) {
            targetW = logW;   // keep the weight actually used for the next set
        }

        if (setNo < e["s"]) {
            setNo += 1;
            startRest(e["rest"]);
        } else if (exIdx + 1 < ex.size()) {
            exIdx += 1;
            setNo = 1;
            targetW = current().hasKey("w") ? current()["w"].toFloat() : null;
            startRest(e["rest"] > 0 ? e["rest"] : REST_BETWEEN_EXERCISES);
        } else {
            state = ST_DONE;
            buzz(2);
        }
        WatchUi.requestUpdate();
    }

    function writeLap(name, s) {
        if (session == null) {
            return;
        }
        fieldEx.setData(name.length() > 23 ? name.substring(0, 23) : name);
        fieldReps.setData(s["r"]);
        fieldKg.setData(s.hasKey("w") ? s["w"] : 0.0);
        session.addLap();
    }

    function startRest(seconds) {
        restTotal = seconds;
        restLeft = seconds > 0 ? seconds : 0;
        state = ST_REST;
    }

    function endRest() {
        setStart = Time.now().value();
        state = ST_SET;
        WatchUi.requestUpdate();
    }

    function onTick() {
        if (state == ST_REST) {
            if (restTotal > 0) {
                restLeft -= 1;
                if (restLeft == 10) {
                    buzz(0);
                }
                if (restLeft <= 0) {
                    buzz(2);
                    endRest();
                    return;
                }
            } else {
                restLeft += 1;   // free rest: count up
            }
        }
        WatchUi.requestUpdate();
    }

    function skipExercise() {
        if (free || exIdx + 1 >= ex.size()) {
            state = ST_DONE;
        } else {
            exIdx += 1;
            setNo = 1;
            targetW = current().hasKey("w") ? current()["w"].toFloat() : null;
            setStart = Time.now().value();
            state = ST_SET;
        }
        WatchUi.requestUpdate();
    }

    function stopTimer() {
        if (timer != null) {
            timer.stop();
            timer = null;
        }
    }

    function save() {
        finalElapsed = elapsed();
        stopTimer();
        if (session != null) {
            session.stop();
            session.save();
            session = null;
        }
        state = ST_SAVED;
        buzz(1);
        if (sets.size() == 0) {
            sendStatus = "";
        } else {
            sendStatus = "Enviando...";
            sendLog({"start" => startEpoch, "dur" => finalElapsed, "name" => activityName(), "sets" => sets});
        }
        WatchUi.requestUpdate();
    }

    function discard() {
        stopTimer();
        if (session != null) {
            session.stop();
            session.discard();
            session = null;
        }
        System.exit();
    }

    function onAppStop() {
        if (session != null && session.isRecording()) {
            save();
        }
    }

    // ------------------------------------------------------------------
    // Sending the performed sets
    // ------------------------------------------------------------------

    function sendLog(body) {
        Application.Storage.setValue("pending", body);
        Communications.makeWebRequest(
            Secrets.SERVER_URL + "/watch/log?k=" + Secrets.WATCH_KEY,
            body,
            {
                :method => Communications.HTTP_REQUEST_METHOD_POST,
                :headers => {"Content-Type" => Communications.REQUEST_CONTENT_TYPE_JSON},
                :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
            },
            method(:onLogSent)
        );
    }

    function onLogSent(code, data) {
        if (code == 200) {
            Application.Storage.deleteValue("pending");
            sendStatus = "Enviado a Garmin";
        } else {
            sendStatus = "Se enviara al conectar";
        }
        WatchUi.requestUpdate();
    }

    function resendPending() {
        var body = Application.Storage.getValue("pending");
        if (body != null) {
            sendLog(body);
        }
    }

    function buzz(kind) {
        if (!(Attention has :vibrate)) {
            return;
        }
        var p;
        if (kind == 0) {
            p = [new Attention.VibeProfile(50, 200)];
        } else if (kind == 1) {
            p = [new Attention.VibeProfile(100, 300)];
        } else {
            p = [
                new Attention.VibeProfile(100, 400),
                new Attention.VibeProfile(0, 150),
                new Attention.VibeProfile(100, 400)
            ];
        }
        Attention.vibrate(p);
    }
}

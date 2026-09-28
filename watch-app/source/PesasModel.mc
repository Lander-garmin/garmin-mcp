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
import Toybox.Time.Gregorian;
import Toybox.Timer;
import Toybox.WatchUi;

// Session states
const ST_LOADING = 0;   // fetching today's plan
const ST_NOPLAN = 1;    // nothing scheduled today
const ST_ERROR = 2;     // could not reach the server
const ST_READY = 3;     // plan loaded, choose Realizar / Ver
const ST_WAIT = 4;      // "Pulsa START para empezar"
const ST_SET = 5;       // doing a set
const ST_REST = 6;      // resting between sets
const ST_DONE = 7;      // all sets done, START to save
const ST_SAVED = 8;     // saved, sending sets

const DEFAULT_REST_BETWEEN_EXERCISES = 90;

class PesasModel {
    var state = ST_LOADING;
    var message = "";
    var plan = null;          // Dictionary from /watch/today
    var ex = [];              // exercise list
    var exIdx = 0;
    var setNo = 1;
    var curR = 0;             // reps for the set being done
    var curW = null;          // kg for the set being done (null = bodyweight)
    var restTotal = 0;
    var restLeft = 0;
    var restCountUp = 0;
    var sets = [];            // performed sets sent to the server
    var lapPending = false;   // a set is done but its lap is not written yet
    var session = null;
    var fieldEx = null;
    var fieldReps = null;
    var fieldKg = null;
    var sessionStartMs = 0;
    var sessionStart = 0;
    var setStart = 0;
    var timer = null;
    var sendStatus = "";
    var freeSession = false;
    var finalElapsed = 0;

    function initialize() {
    }

    // ------------------------------------------------------------------
    // Plan
    // ------------------------------------------------------------------

    function fetchPlan() {
        state = ST_LOADING;
        message = "Cargando entreno...";
        Communications.makeWebRequest(
            SERVER_URL + "/watch/today",
            {"k" => WATCH_KEY},
            {
                :method => Communications.HTTP_REQUEST_METHOD_GET,
                :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
            },
            method(:onPlan)
        );
    }

    function onPlan(code, data) {
        if (code == 200 && data != null && data["ok"] == true) {
            if (data.hasKey("none")) {
                state = ST_NOPLAN;
                message = "Hoy no hay gym en el calendario";
            } else {
                Application.Storage.setValue("plan", data);
                usePlan(data, "");
            }
        } else {
            // No phone / no signal: use today's plan if it was downloaded earlier.
            var cached = Application.Storage.getValue("plan");
            if (cached != null && todayIso().equals(cached["date"])) {
                usePlan(cached, "Sin movil: entreno guardado");
            } else {
                state = ST_ERROR;
                message = "Sin conexion con el movil";
            }
        }
        WatchUi.requestUpdate();
    }

    function usePlan(data, note) {
        plan = data;
        ex = data["ex"];
        message = note;
        if (ex == null || ex.size() == 0) {
            state = ST_NOPLAN;
            message = "El entreno de hoy no tiene ejercicios";
            return;
        }
        state = ST_READY;
        WatchUi.pushView(new PlanMenu(), new PlanMenuDelegate(), WatchUi.SLIDE_IMMEDIATE);
    }

    function todayIso() {
        var d = Gregorian.info(Time.now(), Time.FORMAT_SHORT);
        return d.year.format("%04d") + "-" + d.month.format("%02d") + "-" + d.day.format("%02d");
    }

    function planName() {
        if (plan == null) {
            return "Gym libre";
        }
        return plan["name"];
    }

    // "Plan X 30/09 Gym Push 70 min" (or "... Pesas Push ...") -> "Gym Push"
    function shortName() {
        var n = planName();
        var i = n.find("Gym ");
        var skip = 4;
        if (i == null) {
            i = n.find("Pesas ");
            skip = 6;
        }
        if (i == null) {
            return "Gym";
        }
        var rest = n.substring(i + skip, n.length());
        var sp = rest.find(" ");
        var word = (sp == null) ? rest : rest.substring(0, sp);
        if (word.length() == 0) {
            return "Gym";
        }
        var name = "Gym " + word;
        return name.length() > 15 ? name.substring(0, 15) : name;
    }

    function startFreeSession() {
        freeSession = true;
        plan = null;
        ex = [{"n" => "Serie", "c" => "UNKNOWN", "e" => "UNKNOWN", "s" => 99, "rest" => 0}];
        chooseRealizar();
    }

    function chooseRealizar() {
        exIdx = 0;
        setNo = 1;
        loadTargets();
        state = ST_WAIT;
        WatchUi.requestUpdate();
    }

    function current() {
        return ex[exIdx];
    }

    function loadTargets() {
        var e = current();
        curR = e.hasKey("r") ? e["r"] : 0;
        curW = e.hasKey("w") ? e["w"].toFloat() : null;
    }

    // ------------------------------------------------------------------
    // Recording
    // ------------------------------------------------------------------

    function startSession() {
        Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE]);
        session = ActivityRecording.createSession({
            :name => shortName(),
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
        sessionStartMs = System.getTimer();
        sessionStart = Time.now().value();
        setStart = sessionStart;
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
        return (System.getTimer() - sessionStartMs) / 1000;
    }

    function heartRate() {
        var info = Activity.getActivityInfo();
        if (info != null && info.currentHeartRate != null) {
            return info.currentHeartRate;
        }
        return null;
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
                restCountUp += 1;
            }
        }
        WatchUi.requestUpdate();
    }

    // UP / DOWN during a set change the load (or the reps if bodyweight);
    // during the rest they correct the reps of the set just done.
    function adjust(delta) {
        if (state == ST_SET) {
            if (curW != null) {
                curW = curW + 2.5 * delta;
                if (curW < 0) {
                    curW = 0.0;
                }
            } else {
                curR = curR + delta;
                if (curR < 0) {
                    curR = 0;
                }
            }
        } else if (state == ST_REST && sets.size() > 0) {
            var last = sets[sets.size() - 1];
            var r = last["r"] + delta;
            last["r"] = r < 0 ? 0 : r;
        }
        WatchUi.requestUpdate();
    }

    function completeSet() {
        var now = Time.now().value();
        var e = current();
        var s = {"c" => e["c"], "e" => e["e"], "r" => curR, "t" => setStart, "d" => now - setStart};
        if (curW != null) {
            s["w"] = curW;
        }
        sets.add(s);
        lapPending = true;

        if (setNo < e["s"]) {
            setNo += 1;
            startRest(e["rest"]);
        } else if (exIdx + 1 < ex.size()) {
            exIdx += 1;
            setNo = 1;
            loadTargets();
            var r = e["rest"];
            startRest(r > 0 ? r : DEFAULT_REST_BETWEEN_EXERCISES);
        } else {
            writeLap();
            state = ST_DONE;
            buzz(2);
        }
        WatchUi.requestUpdate();
    }

    function startRest(seconds) {
        restTotal = seconds;
        restLeft = seconds;
        restCountUp = 0;
        state = ST_REST;
    }

    function endRest() {
        writeLap();
        setStart = Time.now().value();
        state = ST_SET;
        WatchUi.requestUpdate();
    }

    // One lap per set (set + following rest), tagged with exercise, reps, kg.
    function writeLap() {
        if (!lapPending || session == null || sets.size() == 0) {
            return;
        }
        var last = sets[sets.size() - 1];
        fieldEx.setData(exerciseLabel(last["e"]));
        fieldReps.setData(last["r"]);
        fieldKg.setData(last.hasKey("w") ? last["w"] : 0.0);
        session.addLap();
        lapPending = false;
    }

    function exerciseLabel(enumName) {
        for (var i = 0; i < ex.size(); i += 1) {
            if (ex[i]["e"].equals(enumName)) {
                var n = ex[i]["n"];
                return n.length() > 23 ? n.substring(0, 23) : n;
            }
        }
        return "Serie";
    }

    function skipExercise() {
        if (exIdx + 1 < ex.size()) {
            writeLap();
            exIdx += 1;
            setNo = 1;
            loadTargets();
            setStart = Time.now().value();
            state = ST_SET;
        } else {
            writeLap();
            state = ST_DONE;
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
        writeLap();
        finalElapsed = elapsed();
        stopTimer();
        if (session != null) {
            session.stop();
            session.save();
            session = null;
        }
        state = ST_SAVED;
        buzz(1);
        if (freeSession || sets.size() == 0) {
            sendStatus = "Sesion guardada";
        } else {
            sendStatus = "Enviando series...";
            sendLog(buildLog());
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
        // Never lose a running session if the app is closed by the system.
        if (session != null && session.isRecording()) {
            save();
        }
    }

    // ------------------------------------------------------------------
    // Sending the performed sets
    // ------------------------------------------------------------------

    function buildLog() {
        return {"start" => sessionStart, "dur" => elapsed(), "name" => shortName(), "sets" => sets};
    }

    function sendLog(body) {
        Application.Storage.setValue("pending", body);
        Communications.makeWebRequest(
            SERVER_URL + "/watch/log?k=" + WATCH_KEY,
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
            sendStatus = "Series enviadas";
        } else {
            sendStatus = "Se enviaran luego (" + code.toString() + ")";
        }
        WatchUi.requestUpdate();
    }

    function resendPending() {
        var body = Application.Storage.getValue("pending");
        if (body != null) {
            sendLog(body);
        }
    }

    // ------------------------------------------------------------------

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

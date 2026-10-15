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
const ST_SET = 2;       // doing a set: START when finished (timed set: START = play)
const ST_LOG = 3;       // note reps and kg of the set just done
const ST_REST = 4;      // rest countdown
const ST_DONE = 5;      // all sets done: START to rate and save
const ST_SAVED = 6;     // saved
const ST_TIMER = 7;     // timed set running: countdown, closes by itself

const WEIGHT_STEP = 2.5;
const REST_BETWEEN_EXERCISES = 90;

// The plan comes as blocks: {"s" sets, "rest" s, "x" [exercises], "wu" 1 = warm-up}.
// A block with several exercises is a superset: x[0], x[1], ... then the rest,
// "s" rounds. The walk is precomputed as a list of [block, exercise, round].
class PesasModel {
    var state = ST_LOADING;
    var plan = null;
    var blocks = [];
    var seq = [];
    var pos = 0;
    var free = false;
    var offline = false;
    var targetW = null;       // kg for the current set (null = bodyweight)
    var lastW = {};           // block*100+exercise -> kg used last time
    var logField = 0;         // 0 = reps, 1 = kg
    var logR = 0;
    var logW = null;
    var restTotal = 0;
    var restLeft = 0;
    var timerLeft = 0;
    var timedDone = 0;        // seconds a timed set actually lasted
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
    var feel = null;
    var rpe = null;

    function initialize() {
    }

    // ------------------------------------------------------------------
    // Plan
    // ------------------------------------------------------------------

    function fetchPlan() {
        state = ST_LOADING;
        Communications.makeWebRequest(
            Secrets.SERVER_URL + "/watch/today",
            {"k" => Secrets.WATCH_KEY, "date" => localDate(), "v" => 2},
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
            schedulePlanRefresh();
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

    // Accepts the block format (v2) and the old one-entry-per-exercise list.
    function planBlocks(data) {
        if (data == null || data.hasKey("none")) {
            return [];
        }
        if (data["b"] instanceof Array) {
            return data["b"];
        }
        var out = [];
        var old = data["ex"];
        if (old instanceof Array) {
            for (var i = 0; i < old.size(); i += 1) {
                var e = old[i];
                out.add({"s" => e["s"], "rest" => e["rest"], "x" => [e]});
            }
        }
        return out;
    }

    function usePlan(data) {
        blocks = planBlocks(data);
        if (blocks.size() > 0) {
            plan = data;
            free = false;
        } else {
            plan = null;
            free = true;
            blocks = [{"s" => 999, "rest" => 0, "x" => [{"n" => "Ejercicio", "c" => "UNKNOWN", "e" => "UNKNOWN"}]}];
        }
        seq = [];
        for (var b = 0; b < blocks.size(); b += 1) {
            var rounds = blocks[b]["s"];
            var n = blocks[b]["x"].size();
            for (var r = 1; r <= rounds; r += 1) {
                for (var x = 0; x < n; x += 1) {
                    seq.add([b, x, r]);
                }
            }
        }
        pos = 0;
        lastW = {};
        loadTarget();
        state = ST_START;
    }

    function block() {
        return blocks[seq[pos][0]];
    }

    function current() {
        return block()["x"][seq[pos][1]];
    }

    function round() {
        return seq[pos][2];
    }

    function isWarmup() {
        return block().hasKey("wu");
    }

    function isSuperset() {
        return block()["x"].size() > 1;
    }

    function isTimed() {
        return current().hasKey("sec");
    }

    function isDistance() {
        return current().hasKey("m");
    }

    function targetReps() {
        var e = current();
        if (e.hasKey("r")) {
            return e["r"];
        }
        return 0;
    }

    function key() {
        return seq[pos][0] * 100 + seq[pos][1];
    }

    // Weight for the current set: what was used last time on this exercise, else the plan.
    function loadTarget() {
        var e = current();
        if (lastW.hasKey(key())) {
            targetW = lastW[key()];
        } else {
            targetW = e.hasKey("w") ? e["w"].toFloat() : null;
        }
    }

    // Number of exercises in the plan (warm-up sets not counted).
    function exerciseCount() {
        var n = 0;
        for (var b = 0; b < blocks.size(); b += 1) {
            if (!blocks[b].hasKey("wu")) {
                n += blocks[b]["x"].size();
            }
        }
        return n;
    }

    // "Plan X 30/09 Pesas Push 70 min" -> "Push"
    function title() {
        if (plan == null) {
            return "Sesion libre";
        }
        var n = plan["name"];
        var i = n.find("Pesas ");
        var skip = 6;
        if (i == null) {
            i = n.find("Gym ");
            skip = 4;
        }
        if (i == null) {
            return n.length() > 16 ? n.substring(0, 16) : n;
        }
        var rest = n.substring(i + skip, n.length());
        var sp = rest.find(" ");
        return sp == null ? rest : rest.substring(0, sp);
    }

    function activityName() {
        return plan == null ? "Pesas" : "Pesas " + title();
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

    // START on the set screen.
    function setDone() {
        if (isTimed()) {
            // Play: the countdown runs and closes the set by itself.
            setStart = Time.now().value();
            timerLeft = current()["sec"];
            state = ST_TIMER;
            buzz(1);
            WatchUi.requestUpdate();
            return;
        }
        afterSet();
    }

    // START during a timed set: stop it early.
    function stopTimed() {
        finishTimed();
    }

    function finishTimed() {
        timedDone = Time.now().value() - setStart;
        afterSet();
    }

    // The set is over: note what was done (reps and/or kg), or confirm directly.
    function afterSet() {
        logR = targetReps();
        logW = targetW;
        if (free) {
            logW = 0.0;
            if (sets.size() > 0) {
                var last = sets[sets.size() - 1];
                logR = last.hasKey("r") ? last["r"] : 0;
                logW = last.hasKey("w") ? last["w"] : 0.0;
            }
        }
        var repsField = !isTimed() && !isDistance();
        if (!repsField && logW == null) {
            confirmSet();   // timed / distance set without weight: nothing to note
            return;
        }
        logField = repsField ? 0 : 1;
        state = ST_LOG;
        WatchUi.requestUpdate();
    }

    function hasRepsField() {
        return !isTimed() && !isDistance();
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
        var s = {"c" => e["c"], "e" => e["e"], "n" => e["n"], "t" => setStart};
        if (isTimed()) {
            s["sec"] = e["sec"];
            s["d"] = timedDone;
        } else if (isDistance()) {
            s["m"] = e["m"];
            s["d"] = now - setStart;
        } else {
            s["r"] = logR;
            s["d"] = now - setStart;
        }
        if (logW != null && !(free && logW == 0.0)) {
            s["w"] = logW;
        }
        sets.add(s);
        writeLap(e["n"], s);
        if (logW != null) {
            lastW[key()] = logW;   // keep the weight actually used for the next round
        }
        advance();
        WatchUi.requestUpdate();
    }

    // Next step of the walk: next exercise of the superset, or the rest.
    function advance() {
        if (pos + 1 >= seq.size()) {
            state = ST_DONE;
            buzz(2);
            return;
        }
        var b = block();
        var lastOfRound = seq[pos][1] == b["x"].size() - 1;
        var nextBlock = seq[pos + 1][0] != seq[pos][0];
        pos += 1;
        loadTarget();
        if (!lastOfRound) {
            setStart = Time.now().value();
            state = ST_SET;   // superset: straight to the next exercise
            buzz(0);
            return;
        }
        var rest = b["rest"];
        if (rest == 0 && nextBlock) {
            rest = REST_BETWEEN_EXERCISES;
        }
        startRest(rest);
    }

    function writeLap(name, s) {
        if (session == null) {
            return;
        }
        fieldEx.setData(name.length() > 23 ? name.substring(0, 23) : name);
        fieldReps.setData(s.hasKey("r") ? s["r"] : 0);
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
        } else if (state == ST_TIMER) {
            timerLeft -= 1;
            if (timerLeft <= 0) {
                buzz(2);
                finishTimed();
                return;
            }
            if (timerLeft == 10) {
                buzz(0);
            }
        }
        WatchUi.requestUpdate();
    }

    // Pause menu: skip what is left of the current block.
    function skipExercise() {
        var b = seq[pos][0];
        while (pos < seq.size() && seq[pos][0] == b) {
            pos += 1;
        }
        if (free || pos >= seq.size()) {
            pos = seq.size() - 1;
            state = ST_DONE;
        } else {
            loadTarget();
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

    // After the rating menus (feel / effort); nulls when skipped.
    function saveRated(f, r) {
        feel = f;
        rpe = r;
        save();
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
            var body = {"start" => startEpoch, "dur" => finalElapsed, "name" => activityName(), "sets" => sets};
            if (feel != null) {
                body["feel"] = feel;
            }
            if (rpe != null) {
                body["rpe"] = rpe;
            }
            sendLog(body);
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

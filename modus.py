# Your AI for CTF must inherit from the base Commander class.  See how this is
# implemented by looking at the commander.py in the ./api/ folder.
from api import Commander
from api import commands
from api import Vector2
import logging
import sys
import math
import traceback
from collections import deque


def exit_except(fn):
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception, e:
            print "Exception!!", e
            print traceback.format_exc()
            print sys.exc_info()[0]
            raw_input("Press Enter to continue...")
            exit(0)
    return wrapped


def anglebetween(v1, v2):
    try:
        cos = v1.dotProduct(v2) / (v1.length() * v2.length())
        angle = math.acos(cos)
    except ZeroDivisionError:
        return math.acos(0)
    except ValueError:
        return math.acos(0)
    except Exception:
        return math.acos(0)
    return angle


def getclosest(closest_to, listofthings):
    """ closest_to: a vector position
    listofthings: list of objects which ave a position"""
    if listofthings:
        _, closest = sorted([(x.position.distance(closest_to), x) for x in listofthings])[0]
        return closest
    return None


class ModusCommander(Commander):
    """
    Rename and modify this class to create your own commander and add mycmd.Placeholder
    to the execution command you use to run the competition.
    """

    tickcount = 1

    def initialize(self):
        """Use this function to setup your bot before the game starts."""
        self.verbose = True    # display the command descriptions next to the bot labels

        filelogLevel = logging.DEBUG
        STDlogLevel = logging.DEBUG

        class ContextFilter(logging.Filter):
            def filter(self, record):
                record.tick = ModusCommander.tickcount
                return True

        filehandler = self.log.handlers[0]
        stdoutloghandler = logging.StreamHandler(sys.stdout)
        c = ContextFilter()
        filehandler.addFilter(c)
        filehandler.setFormatter(logging.Formatter('$(tick)d: %(levelname)s: %(message)s'))
        filehandler.setLevel(filelogLevel)
        stdoutloghandler.addFilter(c)
        stdoutloghandler.setFormatter(logging.Formatter('%(tick)d: %(levelname)s: %(message)s'))
        stdoutloghandler.setLevel(STDlogLevel)
        self.log.addHandler(stdoutloghandler)

        self.seenodefenders = True
        self.groups = {"defenders": set(), "returningflag": set(), "defending": set(), "defendone": set(), "defendtwo": set(), "watching": set(), "overpower": set(),
                       "waiting": set(), "charging": set(), "attackingflag": set(), "aimatenemy": set(), "attacking": set(),
                       "flagspawn": set(), "chargingflagspawn": set(), "hunting": set(), "flagchaser": set(), "flagcutoff": set()}

        first, second = self.game.enemyTeam.botSpawnArea
        self.enemySpawn = first.midPoint(second)  # NOQA

        self.timetilnextrespawn = self.game.match.timeToNextRespawn

        self.attackcount = 0
        self.log.info("Modusbots are %s", repr([b.name for b in self.game.bots_alive]))

        self.numberofbots = len(self.game.bots_alive)

        self.events = self.game.match.combatEvents

        self.timesincelastevent = 0

        self.currentcommand = {b: None for b in self.game.bots_alive}
        self.killcount = 0
        self.losscount = 0
        self.needsorders = set()

        self.pairs = {}

        self.dead = set()
        self.allbots = self.game.bots.values()
        self.mybots = [bot for bot in self.game.bots.values() if bot.team == self.game.team]
        self.enemybots = [bot for bot in self.game.bots.values() if bot.team != self.game.team]

        self.enemyfullD = False

        self.lastaimtime = 0.0

        self.defendspot = self.towards(self.breadthfirstsearch(self.game.team.flagSpawnLocation, self.iswall, self.level.firingDistance),
                                       self.game.team.flagSpawnLocation, self.level.characterRadius)

        self.maxnumberofdefenders = 2
        if self.game.bots_alive < 3:
            self.maxnumberofdefenders = 1
        if self.game.bots_alive < 2:
            self.maxnumberofdefenders = 0
        self.numberofdefenders = 0  # We don't start with any

    def addtogroup(self, bot, group):
        self.clearfromgroups(bot)
        self.log.debug("Adding {} to group {}".format(bot.name, group))
        if group in ["defending", "watching", "aimatenemy", "defendone", "defendtwo"]:
            self.log.debug("adding {} to defenders because adding to {}".format(bot.name, group))
            self.groups["defenders"].add(bot)
        if group in ["watching", "aimatenemy", "defendone", "defendtwo"]:
            self.groups["defending"].add(bot)
        self.groups[group].add(bot)

    def issuesafe(self, command, bot, target=None, facingDirection=None, lookAt=None, description=None, group=None, safe=True):
        if bot in self.dead:
            self.log.error("deadbot {} issued an order!".format("bot.name"))

        if target:
            if safe:
                safetarget = self.findFree(target)
            else:
                safetarget = target

        self.needsorders.discard(bot)
        if bot.name in self.moved_this_turn:
            self.log.warn("do not issue order to {}, already issued this turn, passing".format(bot.name))
            return
        self.moved_this_turn.add(bot.name)
        if bot.state is bot.STATE_SHOOTING:
            self.log.warn("do not issue order to firing bot {}, passing".format(bot.name))
            return
        if bot.state is bot.STATE_TAKINGORDERS:
            self.log.warn("WARNING: reissuing order to {}, {}, {}".format(bot.name, command, description))
            return

        self.log.info("Issuing {} command {}".format(bot.name, description))
        self.currentcommand[bot] = {"command": command, "target": target, "facingDirection": facingDirection,
                                    "lookAt": lookAt, "description": description}
        if group is not None:
            self.addtogroup(bot, group)

        if command == commands.Move:
            self.issue(commands.Move, bot, safetarget, description)
        elif command == commands.Charge:
            self.issue(commands.Charge, bot, safetarget, description)
        elif command == commands.Attack:
            self.issue(commands.Attack, bot, safetarget, lookAt, description)
        elif command == commands.Defend:
            self.issue(commands.Defend, bot, facingDirection, description)

    def blockinfo(self, v):
        cx = int(math.ceil(v.x))
        cy = int(math.ceil(v.y))
        fx = int(math.floor(v.x))
        fy = int(math.floor(v.y))
        max_x = self.level.area[1].x
        max_y = self.level.area[1].y
        fxfy = self.level.blockHeights[fx][fy] if (0 < fx < max_x and 0 < fy < max_y) else 5
        cxfy = self.level.blockHeights[cx][fy] if (0 < cx < max_x and 0 < fy < max_y) else 5
        fxcy = self.level.blockHeights[fx][cy] if (0 < fx < max_x and 0 < cy < max_y) else 5
        cxcy = self.level.blockHeights[cx][cy] if (0 < cx < max_x and 0 < cy < max_y) else 5
        return (fxfy, cxfy,
                fxcy, cxcy)

    def isinablock(self, v, vision=True):
        if vision:
            return all(p > 1 for p in self.blockinfo(v))
        else:
            return all(p > 0 for p in self.blockinfo(v))

    def block(self, v):
        max_x = self.level.area[1].x
        max_y = self.level.area[1].y
        if 0 < v.x < max_x and 0 < v.y < max_y:
            return self.level.blockHeights[int(v.x)][int(v.y)]
        else:
            return 5

    def iswall(self, v):
        if self.block(v) < 2:
            return False
        directions = [Vector2.UNIT_X, Vector2.UNIT_Y, Vector2.NEGATIVE_UNIT_X, Vector2.NEGATIVE_UNIT_Y,
                      Vector2.UNIT_SCALE, -Vector2.UNIT_SCALE,  # diagonals
                      Vector2.UNIT_X - Vector2.UNIT_Y, Vector2.UNIT_Y - Vector2.UNIT_X]  # Other diagonals

        neighbors = [v + d for d in directions]
        blocks = [n for n in neighbors if self.block(n) > 1]
        return len(blocks) == 5

    def isinside(self, v):
        if self.block(v) < 2:
            return False
        directions = [Vector2.UNIT_X, Vector2.UNIT_Y, Vector2.NEGATIVE_UNIT_X, Vector2.NEGATIVE_UNIT_Y,
                      Vector2.UNIT_SCALE, -Vector2.UNIT_SCALE,  # diagonals
                      Vector2.UNIT_X - Vector2.UNIT_Y, Vector2.UNIT_Y - Vector2.UNIT_X]  # Other diagonals

        neighbors = [v + d for d in directions]
        blocks = [n for n in neighbors if self.block(n) > 1]
        return len(blocks) == 8

    def directiontowall(self, v):
        wall = self.breadthfirstsearch(v, self.iswall, self.level.firingDistance)
        return (v - wall).normalized()

    def nearestwall(self, v):
        return self.breadthfirstsearch(v, self.iswall, self.level.firingDistance * 10)

    def wallface(self, v):
        directions = [Vector2.UNIT_X, Vector2.UNIT_Y, Vector2.NEGATIVE_UNIT_X, Vector2.NEGATIVE_UNIT_Y]
        for d in directions:
            if self.block(v + d) < 1:
                return d

    def isawall(self, v, vision=True):
        if vision:
            count = len([p for p in self.blockinfo(v) if p > 1])
        else:
            count = len([p for p in self.blockinfo(v) if p > 0])
        return count == 2

    def walldirection(self, v, vision=True):
        if not self.isawall(v):
            self.log.error("asked direction of a wall which was not a wall!")
        bi = [2 if e > 1 else 0 for e in self.blockinfo(v)]
        if bi[0] == bi[1] > 1:
            return Vector2.UNIT_Y
        if bi[0] == bi[2] > 1:
            return Vector2.UNIT_X
        if bi[3] == bi[2] > 1:
            return Vector2.NEGATIVE_UNIT_Y
        if bi[3] == bi[1] > 1:
            return Vector2.NEGATIVE_UNIT_X

    def breadthfirstsearch(self, starting, testfunction, maxdistance):

        checked = []
        directions = [Vector2.UNIT_X, Vector2.UNIT_Y, Vector2.NEGATIVE_UNIT_X, Vector2.NEGATIVE_UNIT_Y]

        #directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]

        startX, startY = int(starting.x), int(starting.y)

        def ivec(v):
            return Vector2(int(v.x), int(v.y))

        queue = deque()
        queue.append(ivec(starting))
        checked.append(ivec(starting))

        while queue:
            tobetested = queue.popleft()
            if testfunction(tobetested):
                return tobetested
            for d in reversed(directions):
                step = ivec(tobetested + d)
                if step not in checked and self.isinside(step) < 2 and step.distance(starting) < maxdistance:
                    checked.append(step)
                    queue.append(step)

        self.log.error("breadthfirstsearch failed!")
        return None

    def findFree(self, v):
        target = v
        for r in range(1, 50):
            scale = self.level.characterRadius / 2.0
            areaMin = Vector2(target.x - r * scale, target.y - r * scale)
            areaMax = Vector2(target.x + r * scale, target.y + r * scale)
            for _ in range(10):
                position = self.level.findRandomFreePositionInBox((areaMin, areaMax))
                if position:
                    self.log.debug("findFree had to search out to {}".format(r))
                    return position
        return None

    def isinFOV(self, viewer, spot):
        angle = anglebetween(viewer.facingDirection, spot - viewer.position)
        return angle < self.level.FOVangle  # - (math.pi / 12)  # Dont count edges of FOV, 15 degrees here

    def captured(self):
        """Did this team cature the enemy flag?"""
        return self.game.enemyTeam.flag.carrier is not None

    def theyhaveourflag(self):
        """Did they cature our flag?"""
        return self.game.team.flag.carrier is not None

    def respawn(self):
        self.log.info("respawned!")
        self.respawntime = self.game.match.timePassed
        self.killcount = 0
        self.losscount = 0
        self.dead.clear()
        for bot in self.groups["charging"].copy():
            self.giveneworders(bot)
        pass

    def innogroups(self, bot):
        return bot not in set.union(*self.groups.values())

    def clearthedead(self):
        """ remove dead from the groups"""
        self.log.debug("clear the dead")
        alivebots = self.game.bots_alive
        for livingdead in [bot for bot in self.dead if bot.health > 0 and bot.seenlast == 0]:
            self.log.error("Bot {} was proclaimed dead, but isnt. Healthy: {} ! seenlast {}".format(livingdead.name, livingdead.health, livingdead.seenlast))
        for g in self.groups.keys():
            self.groups[g] = set(bot for bot in self.groups[g] if bot in alivebots)

        for deadbot in [bot for bot in self.mybots if (bot.health < 1.0 and bot not in self.dead)]:
            self.log.error("alive bot {} was really dead. health: {}".format(deadbot.name, deadbot.health))
            self.killed(deadbot)
        for deadbot in [bot for bot in self.enemybots if (bot not in self.dead and bot.health < 1 and bot.seenlast == 0.0)]:
            self.log.error("clearing {} because of no health".format(deadbot.name))
            self.killed(deadbot)

    def clearpairs(self, bot):
        self.log.debug("clear {} from pairs ".format(bot.name))
        for k, v in self.pairs.items():
            if bot == k or bot == v:
                self.log.warn("removing {} paired with {}".format(k.name, v.name))
                del self.pairs[k]
                self.giveneworders(k)

    def checkforbadpairs(self):
        self.log.debug("check bad pairs")
        for k, v in self.pairs.items():
            if k in self.dead or v in self.dead:
                self.log.error("member of key pair {} : {} found in dead!".format(k.name, v.name))
            if k.health < 1 or v.health < 1:
                self.log.error("member of key pair {} : {} found without health!".format(k.name, v.name))
                self.log.error("healths. {} : {}".format(k.health, v.health))

    def checkforbadaims(self):
        self.log.debug("check bad pairs")
        for bot in self.groups["aimatenemy"]:
            if bot not in self.pairs.keys():
                self.giveneworders(bot)

    def giveneworders(self, bot):
        self.log.debug("give new orders %s", bot.name)
        self.clearfromgroups(bot)
        self.needsorders.add(bot)

    def clearfromgroups(self, bot_to_remove):
        """ remove bot from all groups"""
        self.log.debug("removing %s from groups", bot_to_remove.name)
        self.clearpairs(bot_to_remove)
        for group in self.groups.keys():
            self.groups[group].discard(bot_to_remove)

    def setnumberofdefenders(self):
        self.log.debug("%d , %d-%d", len(self.enemydefenders), self.numberofbots, self.killcount)
        if self.numberofbots - self.killcount == 0:  # They are all dead
            return 0
        if len(self.enemydefenders) > 0 and len(self.enemydefenders) == self.numberofbots - self.killcount:
            self.log.debug("they are full D")
            self.enemyfullD = True
            for d in self.groups["defenders"].copy():
                self.log.debug("giving {} new orders".format(d.name))
                self.giveneworders(d)
            return 0
        else:
            self.enemyfullD = False
            return min(self.maxnumberofdefenders, self.numberofbots - self.losscount)

    def set_defenders(self):
        newnumberofdefenders = self.setnumberofdefenders()
        if self.numberofdefenders != newnumberofdefenders:
            self.log.warn("number of defendersz changed {} to {}, re-adjusting".format(self.numberofdefenders,
                                                                                       newnumberofdefenders))
            for bot in self.groups["defending"].copy():
                if newnumberofdefenders > self.numberofdefenders:
                    self.numberofdefenders = newnumberofdefenders
                    self.giveneworders(bot)
                else:
                    self.numberofdefenders = newnumberofdefenders
                    self.defend(bot)

        self.numberofdefenders = newnumberofdefenders
        myFlag = self.game.team.flag.position
        if self.needsorders and len(self.groups["defenders"]) < self.numberofdefenders:
            while len(self.groups["defenders"]) < self.numberofdefenders:
                potentialdefenders = [b for b in self.needsorders if b not in self.groups["defenders"]]
                if not potentialdefenders:
                    break
                _, closest_to_my_flag = sorted([(x.position.distance(myFlag), x) for x in potentialdefenders])[0]

                self.defend(closest_to_my_flag)
                self.groups["defenders"].add(closest_to_my_flag)
                self.needsorders.discard(closest_to_my_flag)
                self.moved_this_turn.add(closest_to_my_flag.name)

    def defend(self, defender_bot):
        self.log.debug("defend({})".format(defender_bot.name))
        flag = self.game.team.flag.position

        if self.theyhaveourflag():
            self.recoverflag(defender_bot)
            return

        defendspot = self.defendspot
        if self.defendspot is None or flag.distance(self.game.team.flagSpawnLocation) > 1.0:
            defendspot = flag
        dist = defender_bot.position.distance(defendspot)
        if dist > self.level.firingDistance + 1.0:
            goal = self.findFree(defendspot.midPoint(defender_bot.position))
            goal = defendspot
            self.issuesafe(commands.Charge, defender_bot, goal, description='Get into position to defend', group="defenders")
        elif dist < 0.5:
            self.flagdefend(defender_bot)
        else:
            goal = defendspot
            self.issuesafe(commands.Charge, defender_bot, goal, lookAt=flag, description='Approach', group="defenders", safe=False)

    def vectorfromangle(self, theta):
        return Vector2(math.cos(theta), math.sin(theta))

    def angleofvector(self, v):
        return anglebetween(v, Vector2(0.0, 0.0))

    def rotatevector(self, v, theta):
        newx = math.cos(theta) * v.x - math.sin(theta) * v.y
        newy = math.sin(theta) * v.x + math.cos(theta) * v.y
        return Vector2(newx, newy)

    def wiggledefend(self, bot, direction, descript, grp, factor=3.5):
        wiggleangle = self.level.FOVangle / factor
        directions = [(self.rotatevector(direction, wiggleangle), 1.0), (self.rotatevector(direction, 0.0 - wiggleangle), 1.0)]
        self.issuesafe(commands.Defend, bot, facingDirection=directions, description=descript, group=grp)

    def flagdefend(self, defender_bot):
        mypos = defender_bot.position
        direction = self.enemySpawn - mypos
        # if self.iswall(mypos):
        if mypos.distance(self.nearestwall(mypos)) < 2.0:
            self.log.info("using wall direction!")
            direction = self.wallface(self.nearestwall(mypos))
            defenderangle = (self.level.FOVangle * (1.8 / 3.0))
            halfpi = math.pi / 2.0
            if self.numberofdefenders == 1:
                directions = [(self.rotatevector(direction, halfpi - defenderangle / 2.0), 1.0), (self.rotatevector(direction, -(halfpi - defenderangle / 2.0)), 1.0)]
                self.issuesafe(commands.Defend, defender_bot, facingDirection=directions, description="solo defending", group="defending")
                return
            elif self.numberofdefenders == 2:
                defendernumber = 0
                if defender_bot in self.groups["defendone"]:
                    defendernumber = 1
                elif defender_bot in self.groups["defendtwo"]:
                    defendernumber = 2
                elif self.groups["defendone"]:
                    defendernumber = 2
                else:
                    defendernumber = 1
                # Now run the command for the correc defender
                if defendernumber == 1:
                    self.log.info("I {} am first defender ".format(defender_bot.name))
                    directions = [(self.rotatevector(direction, halfpi - defenderangle / 2.5), 1.0), (self.rotatevector(direction,  defenderangle / 2.0), 1.0)]
                    self.issuesafe(commands.Defend, defender_bot, facingDirection=directions, description="defend_one", group="defendone")
                    return
                elif defendernumber == 2:
                    self.log.info("I {} am second defender ".format(defender_bot.name))
                    directions = [(self.rotatevector(direction, -(halfpi - defenderangle / 2.5)), 1.0), (self.rotatevector(direction, -defenderangle / 2.0), 1.0)]
                    self.issuesafe(commands.Defend, defender_bot, facingDirection=directions, description="defend_two", group="defendtwo")
                    return
                else:
                    self.log.error("Invalid defender number! {}".format(defendernumber))
                    return
            elif self.numberofdefenders == 0:
                self.log.error("why is this called with no defenders?")
                self.clearfromgroups(defender_bot)
                return
            else:
                self.log.error("Invalid num defenders! {}".format(self.numberofdefenders))
                return
        else:
            self.log.warn("Not at a wall!")
            print self.blockinfo(mypos)
            directions = [(direction, 2.0), (-direction, 1.0)]
            self.issuesafe(commands.Defend, defender_bot, facingDirection=directions, description="defending", group="defending")

    def recoverflag(self, defender_bot):
        pass
        flag = self.game.team.flag.position
        mypos = defender_bot.position
        if mypos.distance(flag) < flag.distance(self.game.enemyTeam.flagScoreLocation):
            self.issuesafe(commands.Charge, defender_bot, flag, description="Chasing flag!", group="flagchaser")
        else:
            self.issuesafe(commands.Attack, defender_bot, self.game.enemyTeam.flagScoreLocation, lookAt=flag, description="Cut off flag!", group="flagcutoff")

    def eyeonflag(self, watch_bot):
        if self.groups["watching"]:
            return
        flag = self.game.team.flag.position
        mypos = watch_bot.position
        if watch_bot not in self.groups["watching"]:
            self.wiggledefend(watch_bot, (flag - mypos), 'watching flag', "watching")

    def attack(self, attack_bot):
        self.log.debug("attack({})".format(attack_bot.name))
        enemyFlag = self.game.enemyTeam.flag.position
        enemyFlagSpawn = self.game.enemyTeam.flagSpawnLocation
        mypos = attack_bot.position
        dist = attack_bot.position.distance(enemyFlag)
        if self.numberofbots - self.killcount == 0 and not self.captured():  # They are all dead
            if attack_bot not in self.groups["charging"]:
                self.issuesafe(commands.Charge, attack_bot, enemyFlag, description='Charge enemy flag', group="charging")
                return
        if self.captured():
            if attack_bot.position.distance(enemyFlagSpawn) < self.level.firingDistance / 3.0:
                if attack_bot not in self.groups["flagspawn"]:
                    self.wiggledefend(attack_bot, self.enemySpawn - mypos, 'defending their flagspawn', "flagspawn")
            else:
                if attack_bot not in self.groups["chargingflagspawn"]:
                    self.issuesafe(commands.Attack, attack_bot, enemyFlagSpawn, lookAt=enemyFlagSpawn, description='Attack enemy flagspawn', group="chargingflagspawn")
            return
        # else
        if dist > self.level.firingDistance * 2.0:
            if attack_bot not in self.groups["charging"]:
                goal = enemyFlag + (enemyFlag.midPoint(mypos) - enemyFlag) * 1.2
                first, second = self.game.team.botSpawnArea
                if first.x <= mypos.x <= second.x and first.x <= mypos.x <= second.x:
                    goal = self.towards(mypos, enemyFlag, self.level.firingDistance)
                    look = self.towards(mypos, enemyFlag, self.level.firingDistance * 2)
                    self.issuesafe(commands.Attack, attack_bot, goal, lookAt=look, description='Charge enemy flag', group="charging")
                else:
                    self.issuesafe(commands.Charge, attack_bot, goal, description='Charge enemy flag', group="charging")
        else:
            self.approachflag(attack_bot)

    def overpowerall(self):
        self.log.debug("Overpower go!")
        for bot in self.groups["waiting"].copy():
            self.overpower(bot)

    def overpower(self, attack_bot):
        enemyFlag = self.game.enemyTeam.flag.position

        if attack_bot not in self.groups["overpower"]:
            self.issuesafe(commands.Attack, attack_bot, enemyFlag, lookAt=enemyFlag, description='Overpower defenders', group="overpower")

    def towards(self, frompos, topos, distance=1.0):
        goal = frompos + ((topos - frompos).normalized()) * distance
        return self.findFree(goal)

    def towardsunsafe(self, frompos, topos, distance=1.0):
        goal = frompos + ((topos - frompos).normalized()) * distance
        return goal

    def towards_require_progress(self, frompos, topos, distance=1.0, progress=1.0):
        done = False
        trialdistance = distance
        while(not done):
            goal = frompos + ((topos - frompos).normalized()) * trialdistance
            goal = self.findFree(goal)
            if frompos.distance(goal) > progress and goal.distance(topos) < frompos.distance(topos):
                return goal
            else:
                trialdistance = trialdistance + 0.5
                self.log.debug("trialdistance %d", trialdistance)
        return self.findFree(topos)  # Should never get here

    def approachflag(self, attack_bot):
        self.log.debug("approachflag({})".format(attack_bot.name))
        enemyFlag = self.game.enemyTeam.flag.position
        mypos = attack_bot.position
        FOV = self.level.FOVangle
        out_of_range = [e.position.distance(mypos) > self.level.firingDistance + 2 for e in self.enemydefenders]
        if all(out_of_range) and len(self.enemydefenders) > 0:
            self.log.debug("inch closer {}".format(attack_bot.name))
            if self.groups["waiting"]:
                goal = getclosest(mypos, self.groups["waiting"]).position
                self.issuesafe(commands.Charge, attack_bot, goal, lookAt=enemyFlag, description='Join fellow attacker', group="attacking", safe=False)
            else:
                safedistance = mypos.distance(getclosest(mypos, self.enemydefenders).position) - self.level.firingDistance
                distancetogo = safedistance / 2.0 if safedistance / 2.0 > 1.0 else 1.0
                goal = self.towards_require_progress(mypos, enemyFlag, distance=distancetogo)
                self.issuesafe(commands.Attack, attack_bot, goal, lookAt=enemyFlag, description='Inch closer', group="attacking")
            return
        for enemy in self.enemydefenders:
            if anglebetween(enemy.facingDirection, mypos - enemy.position) <= FOV and mypos.distance(enemy.position) > self.level.firingDistance:
                self.log.debug("not attacking because of {}".format(enemy.name))
                if attack_bot not in self.groups["waiting"]:
                    self.wiggledefend(attack_bot, (enemy.position - mypos), 'Cant attack {}'.format(enemy.name), "waiting", factor=5.0)
                    self.log.warn("pairing {} with {}".format(attack_bot.name, enemy.name))
                    self.pairs[attack_bot] = enemy
                    self.log.debug("waiting {}".format(attack_bot.name))

                return
        if attack_bot not in self.groups["attackingflag"]:
            self.issuesafe(commands.Attack, attack_bot, enemyFlag, lookAt=enemyFlag, description='Attack enemy flag', group="attackingflag")
            self.log.debug("attacking flag {}".format(attack_bot.name))
            return
        # self.clearfromgroups(attack_bot)

    def getseenenemies(self):
        alivebots = self.game.bots_alive
        enemies = set()
        for bot in alivebots:
            enemies.update(bot.visibleEnemies)
        return set(enemies)

    def getseenlivingenemies(self):
        alivebots = self.game.bots_alive
        enemies = set()
        for bot in alivebots:
            enemies.update(bot.visibleEnemies)
        livingenemies = [e for e in enemies if e.health > 0]
        return set(livingenemies)

    def killed(self, killedbot):
        self.dead.add(killedbot)
        self.clearpairs(killedbot)
        self.needsorders.discard(killedbot)
        if killedbot in self.mybots:
            self.losscount += 1
            self.clearfromgroups(killedbot)
        else:
            self.killcount += 1

        killed_enemies = [bot for bot in self.enemybots if bot in self.dead]
        killed_friendlies = [bot for bot in self.mybots if bot in self.dead]

        if self.losscount != len(killed_friendlies):
            self.log.error("killed friendlies doesn match loss count {} {}".format(self.losscount, len(killed_friendlies)))
        if self.killcount != len(killed_enemies):
            self.log.error("killed enemies doesn match kill count {} {}".format(self.killcount, len(killed_enemies)))

    def processevents(self):
        newevents = [e for e in self.game.match.combatEvents if e.time > self.timesincelastevent]
        if len(newevents) < 1:
            return              # do nothing if no new events
        self.log.debug("processing {} events".format(len(newevents)))
        self.timesincelastevent = max([x.time for x in self.game.match.combatEvents])
        for e in [ev for ev in newevents if ev.type == ev.TYPE_KILLED]:
            if e.subject is None or e.instigator is None:
                self.log.error("Error event actors are none subject:{}, instigator:{}".format(e.subject, e.instigator))
                continue
            self.log.info("{} was killed by {}!".format(e.subject.name, e.instigator.name))
            self.killed(e.subject)

        self.log.info("kills: {kill}/{tot}, Losses {loss}/{tot}".format(kill=self.killcount, loss=self.losscount,
                                                                        tot=self.numberofbots))

        for e in [ev for ev in newevents if ev.type == ev.TYPE_FLAG_PICKEDUP]:
            self.log.info("{} pickedup the flag!".format(e.instigator.name))

        for e in [ev for ev in newevents if ev.type == ev.TYPE_FLAG_RESTORED]:
            self.log.info("flag restored!")
            for bot in self.groups["defenders"].copy():
                if self.tickcount > 10:
                    self.giveneworders(bot)
        for e in [ev for ev in newevents if ev.type == ev.TYPE_FLAG_CAPTURED]:
            self.log.info("flag CAPTURED!")
            for bot in self.groups["flagcutoff"].union(self.groups["flagchaser"]).copy():
                self.giveneworders(bot)
        for e in [ev for ev in newevents if ev.type == ev.TYPE_FLAG_DROPPED]:
            self.log.info("flag dropped subject: {} inst: {}!".format(e.subject.name, e.instigator.name))
            self.log.info("flag dropped by {}!".format(e.subject.name))
            for bot in self.groups["flagcutoff"].union(self.groups["flagchaser"]).copy():
                self.giveneworders(bot)

    def checkformovedprey(self):
        for hunter in self.groups["hunting"].copy():
            prey = self.pairs[hunter]
            huntersgoal = self.currentcommand[hunter]["target"]
            if huntersgoal.distance(prey.position) > self.level.firingDistance * 2:
                self.log.warning("prey {} has moved too far from original chase point of {}".format(prey.name, hunter.name))
                self.giveneworders(hunter)

    def checkfordefendingprey(self):
        for hunter in self.groups["hunting"].copy():
            prey = self.pairs[hunter]
            if prey.state == prey.STATE_DEFENDING and self.isinFOV(prey, hunter.position):
                self.giveneworders(hunter)

    def hunt(self):
        prey = [e for e in self.seenenemies if e not in self.enemydefenders and e.state != e.STATE_DEFENDING]

        if len(prey) < 1:
            return

        self.checkformovedprey()
        self.checkfordefendingprey()

        for bot in self.groups["charging"].copy():
            closest = getclosest(bot.position, prey)
            self.issuesafe(commands.Attack, bot, closest.position, lookAt=closest.position, description='hunt {}'.format(closest.name), group="hunting")
            self.pairs[bot] = closest
            self.log.warn("pairing {} with {}".format(bot.name, closest.name))
            # self.hunters[bot.name] = closest.name

    def try_to_overpower(self):
        alivebots = self.game.bots_alive
        if self.enemyfullD:
            if len(self.groups["waiting"]) == len(alivebots):
                if all([w.state == w.STATE_DEFENDING for w in self.groups["waiting"]]):
                    self.overpowerall()
            return
        if len(self.groups["waiting"]) > len(self.enemydefenders):
            self.overpowerall()
        elif len(self.groups["waiting"]) > self.numberofbots - self.killcount:
            self.log.info("overpowering because {} > {}-{}" .format(len(self.groups["waiting"]), self.numberofbots, self.killcount))
            self.overpowerall()
        else:
            # Attack if one cant see any of us
            notlooking = 0
            for bot in self.enemydefenders:
                if len([b for b in self.groups["waiting"] if self.isinFOV(bot, b.position)]) < 1:
                    notlooking += 1
            if len(self.groups["waiting"]) > len(self.enemydefenders) - notlooking:
                self.overpowerall()

    def aimatenemy(self, defender_bot):
        self.log.warn("aimatenemy({})".format(defender_bot.name))
        looked_at = set(self.pairs[k] for k in self.groups["aimatenemy"] if k in self.pairs.keys())
        potential = set(defender_bot.visibleEnemies).difference(looked_at).difference(self.dead)
        closest = getclosest(defender_bot.position, potential)
        direction = closest.position - defender_bot.position
        self.log.warn("pairing {} with {}".format(defender_bot.name, closest.name))
        self.lastaimtime = self.game.match.timePassed
        self.wiggledefend(defender_bot, direction, 'defending against attacker {}!'.format(closest.name),
                          "aimatenemy", factor=8.0)
        self.pairs[defender_bot] = closest

    def react_to_attackers(self):
        for bot in self.groups["defending"]:
            if bot not in self.groups["aimatenemy"].copy():
                looked_at = set(self.pairs[k] for k in self.groups["aimatenemy"] if k in self.pairs.keys())
                potentialvisible = set(bot.visibleEnemies).difference(looked_at).difference(self.dead)
                inrange = [b for b in potentialvisible if b.position.distance(bot.position) < self.level.firingDistance * 2.0]
                movingslow = [b for b in inrange if b.state in (b.STATE_DEFENDING, b.STATE_IDLE, b.STATE_ATTACKING, b.STATE_TAKINGORDERS, b.STATE_SHOOTING)]
                if movingslow:
                    self.aimatenemy(bot)

        for bot in self.groups["aimatenemy"].copy():
            aimed_enemy = self.pairs[bot]
            if aimed_enemy in bot.visibleEnemies:
                self.lastaimtime = self.game.match.timePassed
            else:
                if aimed_enemy in self.dead:
                    self.log.debug("attacker has died clear")
                    self.clearfromgroups(bot)
                    self.defend(bot)
                elif (aimed_enemy.position.distance(bot.position) < self.level.firingDistance * 1.5
                      and aimed_enemy.seenlast < 2.0 and bot.facingDirection == self.currentcommand[bot]["facingDirection"]):
                    self.log.debug("look to where aimed enemy was last seen")
                    self.issuesafe(commands.Defend, bot, facingDirection=aimed_enemy.position - bot.position,
                                   description='defending against last known attacker {}!'.format(aimed_enemy.name), group=None)
                elif self.game.match.timePassed > self.lastaimtime + 2.0:
                    self.log.debug("can no longer see attacker")
                    self.clearfromgroups(bot)
                    self.defend(bot)

    def set_flagwatcher(self):
        if len(self.groups["defending"]) < 1:
            return
        if len(self.enemyattackers) > 0:
            return
        if len(self.groups["defending"]) == self.numberofdefenders:
            closesttoflag = getclosest(self.game.team.flag.position, self.groups["defending"])
            self.eyeonflag(closesttoflag)

    def react_to_defenders(self):
        numenemydefenders = len(self.enemydefenders)
        if numenemydefenders > 0:
            for bot in self.groups["charging"].copy():
                self.giveneworders(bot)
                self.approachflag(bot)

        if numenemydefenders > 0:
            for bot in self.groups["attackingflag"].copy():
                self.giveneworders(bot)
                self.approachflag(bot)

    def reassign_when_flag_dropped(self):
        if not self.captured():
            for bot in self.groups["flagspawn"].union(self.groups["chargingflagspawn"]).copy():
                # self.clearfromgroups(bot)
                self.attack(bot)
                self.moved_this_turn.add(bot.name)

    def order_approachers(self):
        for bot in set(self.groups["waiting"]).union(set(self.groups["attackingflag"])):
            self.approachflag(bot)
            self.moved_this_turn.add(bot.name)

    def order_flag_carrier(self):
        alivebots = self.game.bots_alive
        flagScoreLocation = self.game.team.flagScoreLocation
        for bot in alivebots:
            if bot.flag and bot not in self.groups["returningflag"]:
                self.issuesafe(commands.Charge, bot, flagScoreLocation, description='Turn in the flag', group="returningflag")
                self.moved_this_turn.add(bot.name)
                break

    @exit_except
    def tick(self):
        """Override this function for your own bots.  Here you can
        access all the information in self.game, which includes game
        information, and self.level which includes information about
        the level."""
        flagScoreLocation = self.game.team.flagScoreLocation  # NOQA
        enemyFlag = self.game.enemyTeam.flag.position  # NOQA
        myFlag = self.game.team.flag.position  # NOQA
        enemyFlagSpawn = self.game.enemyTeam.flagSpawnLocation  # NOQA
        alivebots = self.game.bots_alive  # NOQA

        ModusCommander.tickcount += 1
        self.needsorders.clear()

        if self.game.match.timeToNextRespawn > self.timetilnextrespawn:
            self.respawn()
        self.timetilnextrespawn = self.game.match.timeToNextRespawn

        try:
            self.processevents()
        except Exception:
            self.log.error("Exception was thrown in processing events. Possibly malformed events")

        self.clearthedead()

        self.checkforbadpairs()
        self.checkforbadaims()

        # If a bot is defending but new order failed (firing or
        # something) the bot will be stuck without orders forever
        for bot in alivebots:
            if bot.state == bot.STATE_DEFENDING and self.innogroups(bot):
                self.log.warn("defending bot {} is in no groups!!!".format(bot.name))
                self.giveneworders(bot)

        self.seenenemies = self.getseenlivingenemies()

        self.enemydefenders = [e for e in self.seenenemies if e.position.distance(enemyFlag) < self.level.firingDistance and e.state == e.STATE_DEFENDING]

        self.enemyattackers = [e for e in self.seenenemies if e.position.distance(myFlag) < self.level.firingDistance * 2.0]

        self.moved_this_turn = set()

        for bot in self.game.bots_available:
            self.giveneworders(bot)
            # self.needsorders.add(bot)
            # self.clearfromgroups(bot)

        self.order_flag_carrier()

        self.try_to_overpower()

        self.hunt()

        self.react_to_attackers()
        self.react_to_defenders()

        self.set_defenders()
        # self.set_flagwatcher()

        # Stop attacking flag spawn
        self.reassign_when_flag_dropped()

        # rerun approch on waiting and attacking flag
        self.order_approachers()
        # for all bots which aren't currently doing anything
        self.order_remaining()

    def order_remaining(self):
        flagScoreLocation = self.game.team.flagScoreLocation
        for bot in [b for b in self.needsorders if (b not in self.dead)]:
            if bot.flag:
                self.log.info("{} has flag this turn".format(bot.name))
                # if a bot has the flag run to the scoring location
                self.issuesafe(commands.Charge, bot, flagScoreLocation, description='Turn in the flag fail', group="returningflag")
            if bot in self.groups["defenders"]:
                self.log.info("{} is a defender".format(bot.name))
                continue
            else:
                self.log.debug("{} being issued attack in 'order remaining'".format(bot.name))
                self.attack(bot)
        if len(self.needsorders) > 0:
            self.log.warn("failed to give all orders, should not happen!")
            self.log.warn("groups %s", repr(self.groups))
            for k, v in self.groups.iteritems():
                self.log.warn("group key %s, value %s", k, repr([b.name for b in v]))
            self.log.warn("deadbots %s", repr([bot.name for bot in self.dead]))
            self.log.warn("needs orders list remaining %s", repr([bot.name for bot in self.needsorders]))
            for bot in self.needsorders:
                self.clearfromgroups(bot)

    def shutdown(self):
        """Use this function to teardown your bot after the game is over, or perform an
        analysis of the data accumulated during the game."""
        pass

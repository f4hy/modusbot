# Your AI for CTF must inherit from the base Commander class.  See how this is
# implemented by looking at the commander.py in the ./api/ folder.
from api import Commander
from api import commands
import logging
import sys
import random
import math
import traceback


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
    cos = v1.dotProduct(v2) / (v1.length() * v2.length())
    angle = math.acos(cos)
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

    def initialize(self):
        """Use this function to setup your bot before the game starts."""
        self.verbose = True    # display the command descriptions next to the bot labels

        filelogLevel = logging.DEBUG
        STDlogLevel = logging.DEBUG

        filehander = self.log.handlers[0]
        stdoutloghandler = logging.StreamHandler(sys.stdout)
        filehander.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        filehander.setLevel(filelogLevel)
        stdoutloghandler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        stdoutloghandler.setLevel(STDlogLevel)
        self.log.addHandler(stdoutloghandler)

        self.seenodefenders = True
        self.groups = {"defenders": set(), "returningflag": set(), "defending": set(), "watching": set(), "overpower": set(),
                       "waiting": set(), "charging": set(), "attackingflag": set(), "aimatenemy": set(), "attacking": set(),
                       "flagspawn": set(), "chargingflagspawn": set(), "hunting": set()}

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
        self.hunters = {}

        self.pairs = {}

        self.dead = set()
        self.allbots = self.game.bots.values()

        self.enemyfullD = False

        self.maxnumberofdefenders = 2
        if self.game.bots_alive < 3:
            self.maxnumberofdefenders = 1
        if self.game.bots_alive < 2:
            self.maxnumberofdefenders = 0

    def addtogroup(self, bot, group):
        self.clearfromgroups(bot)
        if group in ["defending", "watching", "aimatenemy"]:
            self.groups["defenders"].add(bot)
        if group in ["watching", "aimatenemy"]:
            self.groups["defending"].add(bot)
        self.groups[group].add(bot)

    def issuesafe(self, command, bot, target=None, facingDirection=None, lookAt=None, description=None, group=None):
        if target:
            safetarget = self.level.findNearestFreePosition(target)

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
        self.killcount = 0
        self.losscount = 0
        self.dead.clear()
        pass

    def clearthedead(self):
        """ remove dead from the groups"""
        alivebots = self.game.bots_alive
        for g in self.groups.keys():
            self.groups[g] = set(bot for bot in self.groups[g] if bot in alivebots)
        for deadbot in [bot for bot in self.allbots if bot not in self.dead and bot.health < 1 and bot.seenlast > 0]:
            self.log.debug("clearing {} because of no health".format(deadbot.name))
            self.dead.add(deadbot)
            self.clearfromgroups(deadbot)

    def clearpairs(self, bot):
        for k, v in self.pairs.items():
            if bot == k or bot == v:
                self.giveneworders(k)
                del self.pairs[k]

    def giveneworders(self, bot):
        self.log.debug("give new orders %s", bot.name)
        self.clearfromgroups(bot)
        self.needsorders.add(bot)

    def clearfromgroups(self, bot_to_remove):
        """ remove bot from all groups"""
        self.log.debug("removing %s from groups", bot_to_remove.name)
        for group in self.groups.keys():
            self.groups[group].discard(bot_to_remove)
        if bot_to_remove.name in self.hunters:
            self.log.debug("removing {}".format(bot_to_remove.name))
            del self.hunters[bot_to_remove.name]
            self.needsorders.add(bot_to_remove)

    def setnumberofdefenders(self):
        self.log.debug("%d , %d-%d", len(self.enemydefenders), self.numberofbots, self.killcount)
        if len(self.enemydefenders) == self.numberofbots - self.killcount:
            self.log.debug("they are full D")
            self.enemyfullD = True
            for d in self.groups["defenders"].copy():
                self.giveneworders(d)
            return 0
        else:
            return self.maxnumberofdefenders

    def set_defenders(self):
        self.numberofdefenders = self.setnumberofdefenders()
        self.log.debug("numdefenders %d", self.numberofdefenders)
        self.log.debug("defenders?? %s", repr(self.groups["defenders"]))
        myFlag = self.game.team.flag.position
        if self.needsorders and len(self.groups["defenders"]) < self.numberofdefenders:
            while len(self.groups["defenders"]) < self.numberofdefenders:
                potentialdefenders = [b for b in self.needsorders if b not in self.groups["defenders"]]
                if not potentialdefenders:
                    break
                _, closest_to_my_flag = sorted([(x.position.distance(myFlag), x) for x in potentialdefenders])[0]

                self.defend(closest_to_my_flag)
                print "groups", self.groups
                print "defenders", self.groups["defenders"]
                self.groups["defenders"].add(closest_to_my_flag)
                self.needsorders.discard(closest_to_my_flag)
                self.moved_this_turn.add(closest_to_my_flag.name)

    def defend(self, defender_bot):
        self.log.debug("defend()")
        primelist = [2, 3, 5, 7, 11]
        flag = self.game.team.flag.position
        mypos = defender_bot.position
        dist = defender_bot.position.distance(flag)

        if dist > self.level.firingDistance + 1.0:
            # direction = flag.midPoint(defender_bot.position)-flag
            # goal = flag+flag.midPoint(defender_bot.position).normalized()*(self.level.firingDistance+1.0)
            goal = self.level.findNearestFreePosition(flag.midPoint(defender_bot.position))
            self.issuesafe(commands.Move, defender_bot, goal, description='Get into position to defend', group="defenders")
        elif dist < self.level.firingDistance / 2.0:
            enemySpawn = self.enemySpawn
            directionstolook = [(enemySpawn - mypos, random.choice(primelist)), (mypos - enemySpawn, 0.1)]
            self.issuesafe(commands.Defend, defender_bot, facingDirection=directionstolook, description='defending', group="defending")
        else:
            goal = self.level.findNearestFreePosition(flag.midPoint(mypos))
            #self.issuesafe(commands.Attack, defender_bot, goal, lookAt=flag, description='Slow approach')
            self.issuesafe(commands.Charge, defender_bot, goal, lookAt=flag, description='Approach', group="defenders")

    def aimatenemy(self, defender_bot):
        self.log.debug("aimatenemy()")
        closestattacker = getclosest(defender_bot.position, self.enemyattackers)
        if closestattacker is None:
            self.log.error("closest attacker none!")
            exit(0)
        if self.isinFOV(defender_bot, closestattacker.position) and defender_bot in self.groups["aimatenemy"]:
            return
        #if defender_bot not in self.groups["aimatenemy"]:
        else:
            direction = closestattacker.position - defender_bot.position
            self.issuesafe(commands.Defend, defender_bot, facingDirection=direction,
                           description='defending against attacker {}!'.format(closestattacker.name), group="aimatenemy")
            self.pairs[defender_bot] = closestattacker

    def eyeonflag(self, watch_bot):
        if self.groups["watching"]:
            return
        flag = self.game.team.flag.position
        mypos = watch_bot.position
        self.issuesafe(commands.Defend, watch_bot, facingDirection=(flag - mypos), description='watching flag', group="watching")

    def attack(self, attack_bot):
        enemyFlag = self.game.enemyTeam.flag.position
        enemyFlagSpawn = self.game.enemyTeam.flagSpawnLocation
        mypos = attack_bot.position
        dist = attack_bot.position.distance(enemyFlag)
        if self.captured():
            if attack_bot.position.distance(enemyFlagSpawn) < self.level.firingDistance / 3.0:
                if attack_bot not in self.groups["flagspawn"]:
                    self.issuesafe(commands.Defend, attack_bot, facingDirection=self.enemySpawn - mypos,
                                   description='defending their flagspawn', group="flagspawn")
            else:
                if attack_bot not in self.groups["chargingflagspawn"]:
                    self.issuesafe(commands.Attack, attack_bot, enemyFlagSpawn, lookAt=enemyFlagSpawn, description='Attack enemy flagspawn', group="chargingflagspawn")
            return
        # else
        if dist > self.level.firingDistance * 2.0:
            if attack_bot not in self.groups["charging"]:
                loc = enemyFlag + (enemyFlag.midPoint(mypos) - enemyFlag) * 1.2
                goal = self.level.findNearestFreePosition(loc)
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
        return self.level.findNearestFreePosition(goal)

    def towards_require_progress(self, frompos, topos, distance=1.0, progress=1.0):
        done = False
        trialdistance = distance
        while(not done):
            goal = frompos + ((topos - frompos).normalized()) * trialdistance
            goal = self.level.findNearestFreePosition(goal)
            if frompos.distance(goal) > progress and goal.distance(topos) < frompos.distance(topos):
                return goal
            else:
                trialdistance = trialdistance + 0.5
                self.log.debug("trialdistance %d", trialdistance)
        return self.level.findNearestFreePosition(topos)  # Should never get here

    def approachflag(self, attack_bot):
        self.log.debug("approachflag()")
        enemyFlag = self.game.enemyTeam.flag.position
        mypos = attack_bot.position
        FOV = self.level.FOVangle
        out_of_range = [e.position.distance(mypos) > self.level.firingDistance + 2 for e in self.enemydefenders]
        if all(out_of_range) and len(self.enemydefenders) > 0:
            self.log.debug("inch closer {}".format(attack_bot.name))
            if self.groups["waiting"]:
                goal = getclosest(mypos, self.groups["waiting"]).position
                self.issuesafe(commands.Charge, attack_bot, goal, lookAt=enemyFlag, description='Join fellow attacker', group="attacking")
            else:
                safedistance = mypos.distance(getclosest(mypos, self.enemydefenders).position) - self.level.firingDistance
                distancetogo = safedistance / 2.0 if safedistance / 2.0 > 1.0 else 1.0
                goal = self.towards_require_progress(mypos, enemyFlag, distance=distancetogo)
                self.issuesafe(commands.Attack, attack_bot, goal, lookAt=enemyFlag, description='Inch closer', group="attacking")
            return
        for enemy in self.enemydefenders:
            if anglebetween(enemy.facingDirection, mypos - enemy.position) <= FOV:
                self.log.debug("not attacking because of {}".format(enemy.name))
                if attack_bot not in self.groups["waiting"]:
                    self.issuesafe(commands.Defend, attack_bot, facingDirection=(enemy.position - mypos), description='Cant attack {}'.format(enemy.name), group="waiting")
                    self.pairs[attack_bot] = enemy
                    self.log.debug("waiting {}".format(attack_bot.name))

                return
        if attack_bot not in self.groups["attackingflag"]:
            self.issuesafe(commands.Attack, attack_bot, enemyFlag, lookAt=enemyFlag, description='Attack enemy flag', group="attackingflag")
            self.log.debug("attacking flag {}".format(attack_bot.name))
            return
        self.clearfromgroups(attack_bot)

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

    def processevents(self):
        newevents = [e for e in self.game.match.combatEvents if e.time > self.timesincelastevent]
        if len(newevents) < 1:
            return              # do nothing if no new events
        self.timesincelastevent = max([x.time for x in self.game.match.combatEvents])

        for e in [ev for ev in newevents if e.type == e.TYPE_KILLED]:
            self.dead.add(e.subject)
            self.clearpairs(e.subject)
            if e.subject is None or e.instigator is None:
                continue
            self.log.info("{} was killed by {}!".format(e.subject.name, e.instigator.name))
            if e.instigator.team.name == self.game.team.name:

                self.killcount += 1

                for k, v in list(self.hunters.items()):
                    if e.subject.name == v:
                        self.log.debug("removing {} from hunters".format(k))
                        del self.hunters[k]
                        self.giveneworders(self.game.bots[k])
                        self.needsorders.add(self.game.bots[k])
                        self.clearfromgroups(self.game.bots[k])
            else:
                self.losscount += 1
                self.clearfromgroups(e.subject)

        self.log.info("kills: {kill}/{tot}, Losses {loss}/{tot}".format(kill=self.killcount, loss=self.losscount,
                                                                        tot=self.numberofbots))

        for e in [ev for ev in newevents if e.type == e.TYPE_FLAG_PICKEDUP]:
            self.log.info("{} pickedup the flag!".format(e.instigator.name))

    def checkformovedprey(self):
        for huntername, preyname in self.hunters.items():
            hunter = self.game.bots[huntername]
            prey = self.game.bots[preyname]
            huntersgoal = self.currentcommand[hunter]["target"]
            if huntersgoal.distance(prey.position) > self.level.firingDistance * 2:
                self.log.warning("prey {} has moved too far from original chase point of {}".format(preyname, huntername))
                self.giveneworders(hunter)

    def checkfordefendingprey(self):
        for huntername, preyname in self.hunters.items():
            hunter = self.game.bots[huntername]
            prey = self.game.bots[preyname]
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
            self.hunters[bot.name] = closest.name

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

    def react_to_attackers(self):
        if len(self.enemyattackers) > 0:
            for bot in list(self.groups["defending"]):
                self.aimatenemy(bot)
            # for bot in list(self.groups["defending"])[len(self.enemyattackers):]:
            #     self.aimatenemy(bot)
        else:
            for bot in list(self.groups["aimatenemy"]):
                self.clearfromgroups(bot)
                self.defend(bot)
                self.moved_this_turn.add(bot.name)

    def set_flagwatcher(self):
        if len(self.groups["defending"]) < 1:
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
            for bot in self.groups["flagspawn"].copy():
                self.clearfromgroups(bot)
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
                self.issuesafe(commands.Move, bot, flagScoreLocation, description='Turn in the flag', group="returningflag")
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

        print "tic"
        print [bot.name for bot in self.groups["defenders"]]

        self.needsorders = set()

        self.processevents()
        self.clearthedead()

        if self.game.match.timeToNextRespawn > self.timetilnextrespawn:
            self.respawn()

        self.timetilnextrespawn = self.game.match.timeToNextRespawn

        self.seenenemies = self.getseenlivingenemies()

        self.enemydefenders = [e for e in self.seenenemies if e.position.distance(enemyFlag) < self.level.firingDistance]

        self.enemyattackers = [e for e in self.seenenemies if e.position.distance(myFlag) < self.level.firingDistance * 3.0]

        self.moved_this_turn = set()

        for bot in self.game.bots_available:
            self.needsorders.add(bot)
            self.clearfromgroups(bot)

        self.order_flag_carrier()

        self.try_to_overpower()

        self.hunt()

        self.react_to_attackers()
        self.react_to_defenders()

        self.set_defenders()
        self.set_flagwatcher()

        # Stop attacking flag spawn
        self.reassign_when_flag_dropped()

        # rerun approch on waiting and attacking flag
        self.order_approachers()
        # for all bots which aren't currently doing anything
        self.order_remaining()

        for bot in alivebots:
            if bot.state == bot.STATE_DEFENDING and bot not in self.groups["defenders"]:
                print "error"
                print "defending but not in defenders"
                print bot.name
                print "defenders", [b.name for b in self.groups["defenders"]]
                raw_input("Press Enter to continue...")
                # exit()

    def order_remaining(self):
        flagScoreLocation = self.game.team.flagScoreLocation
        for bot in list(self.needsorders):
            if bot.flag:
                self.log.info("{} has flag this turn".format(bot.name))
                # if a bot has the flag run to the scoring location
                self.issuesafe(commands.Move, bot, flagScoreLocation, description='Turn in the flag fail', group="returningflag")
            if bot in self.groups["defenders"]:
                self.log.info("{} is a defender".format(bot.name))
                continue
            else:
                self.log.debug("{} being issued attack in 'order remaining'".format(bot.name))
                self.attack(bot)
        if len(self.needsorders) > 0:
            self.log.critical("failed to give all orders, should not happen!")
            self.log.critical("groups %s", repr(self.groups))
            for k, v in self.groups.iteritems():
                self.log.critical("group key %s, value %s", k, repr([b.name for b in v]))
            self.log.critical("needs orders list remaining %s", repr([bot.name for bot in self.needsorders]))

    def shutdown(self):
        """Use this function to teardown your bot after the game is over, or perform an
        analysis of the data accumulated during the game."""
        pass

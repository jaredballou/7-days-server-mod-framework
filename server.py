import framework
from framework.player_info import player_info_v4 as player_info
import logging
import math
import pickle
import pygeoip
import random
import re
import sys
import threading
import time

class game_server_info ( object ):
    def __init__ ( self ):
        self.day = 0
        self.hour = 0
        self.mem = ( { }, 0 )
        self.minute = 0
        self.time = ( 0, 0, 0 )

class server ( threading.Thread ):
    def __init__ ( self, framework ):
        super ( server, self ).__init__ ( )
        self.daemon = True
        self.log = logging.getLogger ( __name__ )
        self.__version__ = '0.4.5'
        self.changelog = {
            '0.4.6'  : "Refactor give_stuff.",
            '0.4.5'  : "+get_game_server_summary. Detection of burntzombies, zombieferals.",
            '0.4.4'  : "+get_player_summary, refactor for it.",
            '0.4.3'  : "Added le. Fixed new player info not being saved.",
            '0.4.2'  : "Increased preteleport lag 2 -> 3s. Refactored id update.",
            '0.4.1'  : "Removed enforce_home_radii, moved to sethome.",
            '0.4.0'  : "Make backups of player db every hour.",
            '0.3.16' : "Added display server info functionality. Refactored some parsing using RE.",
            '0.3.15' : "Fixed attributes not being set on new players. Moved some functions to utils.",
            '0.3.14' : "Changed tele to preteleports for map limits and home invasion.",
            '0.3.13' : "Added zombie accountability for giving cash for zombie kills.",
            '0.3.12' : "Fixed error on parsing messages containing colons.",
            '0.3.11' : "Adapted for pm sent from events. Fixed /status bug.",
            '0.3.10' : "Made backend lp more useful. Added +1 karma every 1h. Added karma to /me.",
            '0.3.9' : "Disabled old prison system.",
            '0.3.8' : "Fixed 'lp storm' by only calling lp if needed, not every interval.",
            '0.3.7' : "Preventively change player position after teleport.",
            '0.3.6' : "Added pkill explanations to /me.",
            '0.3.5' : "Added lp after teleport to prevent double teleports.",
            '0.3.4' : "Fixed positions not being saved.",
            '0.3.3' : "Added accounting of play time (/me) and player position.",
            '0.3.2' : "Fixed db update function.",
            '0.3.1' : "Started to ignore command 'restart'.",
            '0.3.0' : "Added pm wrapper function.",
            '0.2.0' : "Upgraded player_info to v3, with stubs to new attributes.",
            '0.1.2' : "Fixed framework.mods being called as list, but now is dict." }

        self.log.info ( "Server module initializing." )

        self.chat = None
        self.entities = { }
        # Other programs might have /keywords that we want to ignore. Put those here.
        self.external_commands = [ 'restart' ]
        self.framework = framework
        self.game_server = game_server_info ( )
        self.latest_id_parse_call = time.time ( )
        self.latest_player_db_backup = 0
        self.shutdown = False

        self.preferences = self.framework.preferences
        self.chat_log_file = self.preferences.chat_log_file
        self.telnet_connection = self.framework.telnet
        self.player_info_file = self.preferences.player_info_file
        self.geoip = pygeoip.GeoIP ( self.preferences.geoip_file, pygeoip.MEMORY_CACHE )
        
        self.day = None
        self.hour = None
        self.minute = None
        self.time = None

        self.commands = { 'about'       : ( self.command_about,
                                            " /about will tell you where to get this mod." ),
                          'curse'       : ( self.curse_player,
                                            " /curse player_name prints an unfriendly message." ),
                          'me'          : ( self.command_me,
                                            " /me will print your info." ),
                          'help'        : ( self.command_help,
                                            " /help shows the list of commands." ),
                          'players'     : ( self.print_players_info,
                                            " /players prints players info." ),
                          'rules'       : ( self.command_rules,
                                            " /rules will print server rules." ),
                          'sos'         : ( self.sos,
                                            " /sos will ask players to help you." ),
                          'starterbase' : ( self.output_starter_base,
                                            " /starterbase will output information about starter base." ),
                          'status'      : ( self.mod_status,
                                            " /status lists running mods." ) }
        
        file_found = True
        try:
            pickle_file = open ( self.player_info_file, 'rb' )
        except FileNotFoundError as e:
            self.log.error ( e )
            self.log.info ( "Creating new player info file." )
            file_found = False

        if ( file_found ):
            self.players_info = pickle.load ( pickle_file )
        else:
            self.players_info = { }

    def __del__ ( self ):
        self.log.warning ( "__del__" )
        if self.chat != None:
            self.chat.close ( )
        pickle_file = open ( self.player_info_file, 'wb' )
        pickle.dump ( self.players_info, pickle_file, pickle.HIGHEST_PROTOCOL )

    def command_about ( self, origin, message ):
        self.say ( "This mod was initiated by Schabracke and is developed by rc." )
        self.say ( "http://github.com/rcbrgs/7-days-server-mod-framework." )
    
    def command_help ( self, msg_origin, msg_content ):
        if len ( msg_content ) > len ( "/help" ):
            for key in self.commands.keys ( ):
                if msg_content [ 6 : -1 ] == key:
                    self.say ( self.commands [ key ] [ 1 ] )
                    return
            for mod_key in self.framework.mods.keys ( ):
                mod = self.framework.mods [ mod_key ] [ 'reference' ]
                for key in mod.commands.keys ( ):
                    if msg_content [ 6 : -1 ] == key:
                        self.say ( mod.commands [ key ] [ 1 ] )
                        return

        command_list = [ ]
        for key in self.commands.keys ( ):
            command_list.append ( key )
        for mod_key in self.framework.mods:
            mod = self.framework.mods [ mod_key ] [ 'reference' ]
            for key in mod.commands.keys ( ):
                command_list.append ( key )

        help_message = "Available commands: "
        for mod_key in sorted ( command_list ):
            help_message += mod_key + " "
        
        self.say ( help_message )
            
    def command_me ( self, player_identifier, message ):
        player = self.get_player ( player_identifier )
        if player == None:
            self.say ( "No such player: %s" % str ( player_identifier ) )
            return
        msg = "%s: " % player.name_sane
        msg += self.geoip.country_code_by_addr ( player.ip )
        if player.home != None:
            msg += ", home at %s" % ( self.framework.utils.get_map_coordinates ( player.home ) )
            if self.framework.utils.calculate_distance ( self.framework.utils.get_coordinates ( player ),
                                                         player.home ) < self.preferences.home_radius:
                msg += ", inside"
            else:
                msg += ", outside"
        if player.languages_spoken:
            msg += ", speaks"
            for language in player.languages_spoken:
                msg += " " + language
        if player.language_preferred:
            msg += ', translation to %s' % player.language_preferred
        msg += ', played %dh' % ( round ( player.online_time / 3600 ) )
        if isinstance ( player.player_kills_explanations, list ):
            msg += ", pkills (total/explained): %d/%d" % (
                player.players, len ( player.player_kills_explanations ) )
        msg += ", karma {:d}".format ( player.karma )
        msg += ", cash {:d}".format ( player.cash )
        msg += "."
        self.say ( msg )

    def command_rules ( self, origin, message ):
        self.say ( "rules are: 1. [FF0000]PVE[FFFFFF] only." )
        self.say ( "                2. No base raping or looting." )
        self.say ( "                3. Do not build / claim inside cities or POIs." )
        self.say ( "All offenses are punishable by permabans, admins judge fairly." )
        self.say ( "Admins are: [400000]Schabracke[FFFFFF], Launchpad, AzoSento, and [FFAAAA]Sitting Duck[FFFFFF]." )
        self.say ( " /sethome sets a 50m radius where only people you invite can stay." )
        self.say ( "Drop on death: everything. Drop on exit: nothing." )
        self.say ( "Player killers are automatically imprisoned." )
        
    def console ( self, message ):
        self.log.debug ( message )
            
        if isinstance ( message, str ):
            inputmsg = message + "\n"
            outputmsg = inputmsg.encode ( 'utf-8' )
        else:
            inputmsg = messagge.decode ( 'ascii' )
            inputmsg = inputmsg + "\n"
            outputmsg = inputmsg.encode ( 'utf-8' )
                
        self.telnet_connection.write ( outputmsg )

    def curse_player ( self, msg_origin, msg_content ):
        target = self.get_player ( msg_content [ 7 : -1 ] )
        if target != None:
            curses = [ "%s can't hit a fat zombie with a blunderbuss.",
                       "%s infected a cheerleader.",
                       "%s, may your path be filled with invisible spikes!",
                       "Can't wait for %s to zombify!",
                       "%s spent 5 SMG clips to kill a zombie crawler.",
                       "That zombie dog is almost as ugly as %s.",
                       "Hard to tell if it's a rabbit or %s screaming.",
                       "Your tea is the weakest, %s!",
                       "I was told %s broke all the crates on the tool shop.",
                       "Break a leg, %s!",
                       "I hope %s loses a claim stone.",
                       "'%s' is just another name for 'zombie dinner'.",
                       "Zombies are looking for brains. Don't worry %s, you're safe!",
                       "Hey %s go away I can't smell my rotten pig with you around.",
                       "You really should find a job %s." ]
            some_msg = curses [ random.randint ( 0, len ( curses ) - 1 ) ]
            self.say ( some_msg % str ( target.name_sane ) )
        else:
            self.say ( "I would never curse such a nice person!" )

    def display_entities ( self ):
        print ( "stal | entty_id | entity_type | lifetime  | remot | dead  | heal | pos" )
        self.wait_entities ( )
        self.framework.get_ent_lock ( )
        for key in self.entities.keys ( ):
            entity = self.entities [ key ]
            self.log.debug ( str ( entity ) )
            print ( "{: 2.1f} | {: <8d} | {: <11s} | {} | {:5s} | {:5s} | {:4d} | {: 5.1f},{: 5.1f},{: 5.1f}".format (
                time.time ( ) - entity.timestamp,
                entity.entity_id,
                entity.entity_type [ : 11 ],
                entity.lifetime,
                entity.remote,
                entity.dead,
                entity.health,
                entity.pos_x, entity.pos_y, entity.pos_z,
            ) )
        self.framework.let_ent_lock ( )

    def display_game_server ( self ):
        print ( self.get_game_server_summary ( ) )
        
    def get_game_server_summary ( self ):
        mi = self.game_server.mem [ 0 ]
        if 'time' not in mi.keys ( ):
            return
        staleness = time.time ( ) - self.game_server.mem [ 1 ]
        msg = "{:.1f}s {:s}m {:s}/{:s}MB {:s}chu {:s}cgo {:s}p/{:s}z/{:s}i/{:s}({:s})e.".format (
            staleness,
            str ( mi [ 'time' ] ), str ( mi [ 'heap' ] ), str ( mi [ 'max' ] ), str ( mi [ 'chunks' ] ),
            str ( mi [ 'cgo' ] ), str ( mi [ 'players' ] ), str ( mi [ 'zombies' ] ), str ( mi [ 'items' ] ),
            str ( mi [ 'entities_1' ] ), str ( mi [ 'entities_2' ] ) ) 

        return msg
                
    def find_nearest_player ( self, playerid ):
        player_distances = { }
        player_inverted_directions = { }
        distances = [ ]
        origin_x = self.players_info [ playerid ].pos_x
        origin_y = self.players_info [ playerid ].pos_y
        for key in self.players_info.keys ( ):
            if key != playerid:
                if self.players_info [ key ].online == True:
                    helper_x = self.players_info [ key ].pos_x
                    helper_y = self.players_info [ key ].pos_y
                    relative_x = origin_x - self.players_info [ key ].pos_x
                    relative_y = origin_y - self.players_info [ key ].pos_y
                    distance = math.sqrt ( relative_x ** 2 + relative_y ** 2 )
                    player_distances [ key ] = distance
                    distances.append ( distance )
                    acos = math.degrees ( math.acos ( relative_x / distance ) )
                    if ( relative_y < 0 ):
                        acos += 180
                    
                    player_inverted_directions [ key ] = int ( ( acos - 90 ) % 360 )
        min_distance = min ( distances )
        for key in player_distances.keys ( ):
            if player_distances [ key ] == min_distance:
                return ( key, min_distance, player_inverted_directions [ key ] )

    def get_nearest_entity ( self, player ):
        self.wait_entities ( )
        self.framework.get_ent_lock ( )
        min_distance = None
        min_entity_id = None
        for key in self.entities.keys ( ):
            if self.entities [ key ].dead == "True":
                continue
            distance = self.framework.utils.calculate_distance ( ( self.entities [ key ].pos_x,
                                                                   self.entities [ key ].pos_y,
                                                                   self.entities [ key ].pos_z ),
                                                                 self.framework.utils.get_coordinates ( player ) )
            self.log.debug ( "distance: {}".format ( distance ) )
            if not min_distance:
                min_distance = distance
            min_distance = min ( min_distance, distance )
            if min_distance == distance:
                min_entity_id = key
        self.log.debug ( "nearest: {}".format ( min_distance ) )

        if min_entity_id not in self.entities.keys ( ):
            self.framework.let_ent_lock ( )
            time.sleep ( 1 )
            self.log.warning ( "Recursively trying to find a near entity." )
            return self.get_nearest_entity ( player )
        
        min_type = self.entities [ min_entity_id ].entity_type
        self.framework.let_ent_lock ( )
        return min_entity_id, min_type
            
    def get_online_players ( self ):
        result = [ ]
        self.framework.get_db_lock ( )
        for key in self.players_info.keys ( ):
            player = self.players_info [ key ]
            if player.online:
                result.append ( player )
        self.framework.let_db_lock ( )
        return result

    def get_player ( self, player ):
        if isinstance ( player, player_info ):
            self.log.debug ( "get_player called with player_info argument by %s" %
                             str ( sys._getframe ( ).f_code.co_name ) )
            return player
        if isinstance ( player, int ):
            if player in self.players_info.keys ( ):
                return self.players_info [ player ]
            else:
                return None
        if not isinstance ( player, str ):
            return None
        possibilities = [ ]
        for key in self.players_info.keys ( ):
            if player == self.players_info [ key ].name:
                return self.players_info [ key ]
            if player.lower ( ) in self.players_info [ key ].name.lower ( ):
                possibilities.append ( key )
        if len ( possibilities ) == 1:
            return self.players_info [ possibilities [ 0 ] ]
        elif len ( possibilities ) > 1:
            self.log.info ( "called from %s" % str ( sys._getframe ( ).f_back.f_code.co_name ) )
            msg = "I can't decide if you mean "
            for entry in possibilities:
                msg += self.players_info [ entry ].name_sane + ", "
            msg = msg [ : -2 ]
            msg += "."
            
            if len ( possibilities ) > 5:
                msg = "I can't decide if you mean "
                for entry in possibilities [ 0 : 2 ]:
                    msg += self.players_info [ entry ].name_sane + ", "
                msg += " or " + str (  len ( possibilities ) - 3 ) + " others."

            self.say ( msg )
            return None
        
        self.log.error ( "No player with identifier %s." % str ( player ) )
        return None

    def get_player_summary ( self, player ):
        if not player.player_kills_explanations:
            player.player_kills_explanations = [ ]
        player_line = "{: 2.1f} | {:<10s} | {:<10d} | {:<6.1f} | {:>2d}/{:<2d} | {:<3d} | {:<6d} | {:<4d} | {:<4d}" .format (
            time.time ( ) - player.timestamp_latest_update,
            str ( player.name_sane [ : 9 ] ),
            player.playerid,
            player.online_time / 3600,
            player.players,
            len ( player.player_kills_explanations ),
            player.karma,
            player.cash,
            player.zombies - player.accounted_zombies,
            player.zombies, )
        return player_line
        
    def get_random_entity ( self ):
        self.wait_entities ( )
        self.framework.get_ent_lock ( )
        random_index = random.choice ( list ( self.entities.keys ( ) ) )
        random_type = self.entities [ random_index ].entity_type
        self.framework.let_ent_lock ( )
        return random_index, random_type
    
    def give_cash ( self, player_id = None, amount = 0 ):
        if amount == 0:
            return
        player = self.get_player ( player_id )
        if player is None:
            return
        try:
            self.log.debug ( player.cash )
            player.cash += amount
            self.log.debug ( player.cash )
        except Exception as e:
            self.log.error ( e )
        
    def give_karma ( self, player_id = None, amount = 0 ):
        if amount == 0:
            return
        player = self.get_player ( player_id )
        if player is None:
            return
        try:
            self.log.debug ( player.karma )
            player.karma += amount
            self.log.debug ( player.karma )
        except Exception as e:
            self.log.error ( e )
    
    def give_player_stuff ( self, player, stuff, quantity ):
        msg = 'give ' + player.name_sane + ' ' + stuff + ' ' + str ( quantity )
        self.log.info ( msg )
        self.console ( msg )

    def greet ( self ):
        self.say ( "%s module %s loaded." % ( self.__class__.__name__,
                                              self.__version__ ) )
        
    def list_players ( self ):
        for key in self.players_info.keys ( ):
            print ( self.players_info [ key ].name )

    def list_nearby_tracks ( self, position ):
        result = [ ]
        for playerid in self.players_info.keys ( ):
            player = self.players_info [ playerid ]
            now = time.time ( )
            if not isinstance ( player.timestamp_latest_update, float ):
                continue
            if ( now - player.timestamp_latest_update ) > ( 24 * 3600 ):
                continue
            if not isinstance ( player.positions, list ):
                continue
            for track in player.positions:
                self.log.debug ( "distance between %s and %s is < 5?" % (
                    str ( track ), str ( position ) ) )
                if ( abs ( position [ 0 ] - track [ 0 ] ) < 5 and
                     abs ( position [ 1 ] - track [ 1 ] ) < 5 and
                     abs ( position [ 2 ] - track [ 2 ] ) < 5 ):
                    result.append ( player.playerid )
                    break
        return result
            
    def list_online_players ( self ):
        print ( "%-4s | %-10s | %-10s | %-6s | %-5s | %-3s | %-6s | uzed | zeds" %
                ( "stal", "name_sane", "playerid", "time", "pks", "kar", "cash" ) )
        print ( "-----+------------+------------+--------+-------+-----+--------+------+------" )
        for player in self.get_online_players ( ):
            print ( self.get_player_summary ( player ) )

    def mod_status ( self, msg_origin, msg_content ):
        self.greet ( )
        for key in self.framework.mods.keys ( ):
            self.framework.mods [ key ] [ 'reference'].greet ( )

    def offline_player ( self, server_log ):
        self.log.info ( "%s" % server_log )

        player_name = server_log.split ( " INF Player " )
        if len ( player_name ) > 1:
            player_name = player_name [ 1 ].split ( " disconnected after " )
            if len ( player_name ) > 1:
                player_name = player_name [ 0 ]
            else:
                player_name = server_log.split ( "', PlayerName='" )
                if len ( player_name ) > 1:
                    player_name = player_name [ 1 ] [ : -2 ]

        if player_name == "":
            return
        
        self.log.info ( "Trying get_player ( %s )" % str ( player_name ) )
        try:
            player = self.get_player ( player_name )
        except Exception as e:
            self.log.error ( "offline_player ( '%s' ): %s." % ( server_log, str ( e ) ) )
            player = None
            
        if player != None:
            player.online = False
            self.log.info ( "%s.online == %s" % ( player.name_sane, str ( player.online ) ) )
            return
        
    def offline_players ( self ):
        for key in self.players_info.keys ( ):
            self.players_info [ key ].online = False

    def output_starter_base ( self, msg_origin, msg_content ):
        self.say ( "To teleport to the starterbase, type /gostart." )
        self.say ( "- Replant what you harvest." )
        self.say ( "- Take what you need, and repay with work around the base." )
        
    def parse_gmsg ( self,
                     msg = None ):
        decoded_msg = msg.decode ( 'utf-8' )
        msg_prefixless = decoded_msg.split ( " INF GMSG: " ) [ 1 ]
        msg_splitted = msg_prefixless.split ( ": " )
        if len ( msg_splitted ) > 1:
            msg_origin = msg_splitted [ 0 ]
            if len ( msg_splitted ) > 2:
                msg_content = ""
                for item in range ( 1, len ( msg_splitted ) - 1 ):
                    msg_content += msg_splitted [ item ] + ": "
                msg_content += msg_splitted [ -1 ] [ : -1 ]
            else:
                msg_content = msg_splitted [ 1 ] [ : -1 ]
            self.log.info ( "CHAT %s: %s" % ( msg_origin, msg_content ) )
            if len ( msg_content ) > 2:
                if msg_content [ 0 : 1 ] == "/":
                    # chat message started with "/"
                    # so it is possibly a command.
                    for key in self.commands.keys ( ):
                        if msg_content [ 1 : len ( key ) + 1 ] == key:
                            self.commands [ key ] [ 0 ] ( msg_origin, msg_content )
                            return
                    for mod_key in self.framework.mods:
                        mod = self.framework.mods [ mod_key ] [ 'reference' ]
                        for key in mod.commands.keys ( ):
                            if msg_content [ 1 : len ( key ) + 1 ] == key:
                                mod.commands [ key ] [ 0 ] ( msg_origin, msg_content )
                                return
                    for external_command in self.external_commands:
                        if msg_content [ 1 : -1 ] == external_command:
                            return
                    self.say ( "Syntax error: %s." % msg_content [ 1 : -1 ] )
                else:
                    for mod_key in self.framework.mods.keys ( ):
                        mod = self.framework.mods [ mod_key ] [ 'reference' ]
                        if mod.__class__.__name__ == "translator":
                            mod.translate ( msg_origin, msg_content [ : -1 ] )

    def player_info_update ( self,
                             level,
                             online,
                             playerid,
                             name,
                             pos_x,
                             pos_y,
                             pos_z,
                             health,
                             ip,
                             deaths,
                             zombies,
                             players,
                             score,
                             steamid ):

        events = [ ]
        
        self.framework.get_db_lock ( )
        if playerid in self.players_info.keys ( ):
            now = time.time ( )
            player = self.players_info [ playerid ]

            # old
            # fixing some Nones
            if player.cash == None:
                player.cash = 0
            if player.karma == None:
                player.karma = 0    
            old_level = player.level
            old_online = player.online
            old_playerid = player.playerid
            old_name = player.name
            old_pos_x = player.pos_x
            old_pos_y = player.pos_y
            old_pos_z = player.pos_z
            old_health = player.health
            old_ip = player.ip
            old_deaths = player.deaths
            old_zombies = player.zombies
            old_players = player.players
            old_score = player.score
            old_steamid = player.steamid
            old_timestamp = player.timestamp_latest_update
            old_online_time = player.online_time
            old_zombies = player.zombies
            
            if isinstance ( old_timestamp, float ):
                added_time = 0
                time_difference = now - old_timestamp
                if time_difference < self.framework.preferences.loop_wait * 10:
                    added_time = time_difference
                total_time = player.online_time
                if isinstance ( total_time, float ):
                    new_total_time = total_time + added_time
                else:
                    new_total_time = added_time
                player.online_time = new_total_time

                # event
                old_minutes = math.floor ( total_time / 3600 )
                new_minutes = math.floor ( new_total_time / 3600 )
                if ( new_minutes > old_minutes ):
                    self.log.info ( "%s played for %d hours." %
                                    ( player.name_sane,
                                      new_minutes ) )
                    self.framework.game_events.player_played_one_hour ( playerid )
                    
            else:
                player.online_time = 0

            player.deaths = deaths
            player.health = health
            player.ip = ip
            player.level = level
            player.name = name
            player.name_sane = self.sanitize ( name )
            player.online = online
            player.pos_x = pos_x
            player.pos_y = pos_y
            player.pos_z = pos_z
            player_positions = player.positions
            if not isinstance ( player_positions, list ):
                player_positions = [ ]
            player_positions.append ( ( pos_x, pos_y, pos_z ) )
            if len ( player_positions ) > 24 * 60 * 60 / self.framework.preferences.loop_wait:
                del ( player_positions [ 0 ] )
            player.positions = player_positions
            #player.rot = rot
            #player.remote = remote
            player.timestamp_latest_update = now
            player.score = int ( score )

            try:
                unaccounted_zombies = zombies - player.accounted_zombies
                if unaccounted_zombies > 100:
                    self.framework.game_events.player_killed_100_zombies ( playerid )
                    player.accounted_zombies += 100
            except Exception as e:
                self.log.error ( "While parsing player {:s}: {:s}.".format (
                    player.name_sane, str ( e ) ) )
                unaccounted_zombies = 0
                player.accounted_zombies = zombies
                
            player.zombies = zombies
                
            if ( old_pos_x != pos_x or
                 old_pos_y != pos_y or
                 old_pos_z != pos_z ):
                events.append ( self.framework.game_events.player_position_changed )

            if ( not old_online ) and online:
                events.append ( self.framework.game_events.player_connected )
                
            #todo: event
            player.players = players
            if old_players < player.players:
                self.log.info ( "Player %s has killed another player!" %
                                player.name_sane )

        else:
            new_player_info = player_info ( health = health,
                                            ip = ip,
                                            name = name,
                                            playerid = playerid,
                                            pos_x = pos_x,
                                            pos_y = pos_y,
                                            pos_z = pos_z,
                                            deaths = deaths,
                                            zombies = int ( zombies ),
                                            players = players,
                                            score = score,
                                            level = level,
                                            steamid = steamid )
            new_player_info.accounted_zombies = zombies
            new_player_info.cash = 0
            new_player_info.home_invitees = [ ]
            new_player_info.inventory_tracker = [ ]
            new_player_info.karma = 0
            new_player_info.name_sane = self.sanitize ( name )
            new_player_info.online = True
            new_player_info.online_time = 0
            new_player_info.player_kills_explanations = [ ]
            new_player_info.positions = [ ( pos_x, pos_y, pos_z ) ]
            new_player_info.timestamp_latest_update = time.time ( )
            
            player = new_player_info
            self.players_info [ playerid ] = player
            
        self.framework.let_db_lock ( )

        for event_function in events:
            event_function ( player )

    def pm ( self, player_id = None, msg = None ):
        destiny_player = self.get_player ( player_id )
        if destiny_player == None:
            self.log.error ( "pm '%s' failed because destiny player invalid." % msg )
            return
        self.console ( 'pm %s "%s"' % ( destiny_player.playerid, msg ) )
        
    def print_players_info ( self, msg_origin, msg_content ):
        for key in self.players_info.keys ( ):
            if self.players_info [ key ].online:
                self.command_me ( key, msg_content )

    def random_online_player ( self ):
        possibilities = [ ]
        for key in self.players_info.keys ( ):
            if self.players_info [ key ].online == True:
                possibilities.append ( key )
        if possibilities == [ ]:
            return None
        random_index = random.randint ( 0, len ( possibilities ) - 1 )
        return self.get_player ( possibilities [ random_index ] )                
                
    def run ( self ):
        while self.shutdown == False:
            self.log.debug ( "Tick" )
            time.sleep ( self.framework.preferences.loop_wait )
                
    def sanitize ( self, original ):
        result = original.replace ( '"', '_' )
        result = result.replace ( "'", '_' )
        return result
                
    def say ( self, msg = None ):
        """
        TELNET MESSAGING String-Conversion Check for Ascii/Bytes and Send-Message Function
        Because Casting Byte to Byte will fail.
        """
        if isinstance ( msg, str ) == True:
            inputmsg = 'say "' + msg.replace ( '"', ' ' ) + '"' + "\n"
            outputmsg = inputmsg.encode ( 'utf-8' )
        else:
            inputmsg = msg.decode('ascii')
            inputmsg = 'say "' + inputmsg.replace ( '"', ' ' ) + '"' + "\n"
            outputmsg = inputmsg.encode ( 'utf-8' )
        self.log.debug ( outputmsg )
        if not self.framework.silence:
            self.telnet_connection.write ( outputmsg )
        else:    
            self.log.info ( "(silenced) %s" % outputmsg )

    def scout_distance ( self, player, entity_id ):
        """
        Will indicate to player how far he is from entity.
        """
        ent_position = None
        self.wait_entities ( )
        self.framework.get_ent_lock ( )
        if entity_id in self.entities.keys ( ):
            ent_position = ( self.entities [ entity_id ].pos_x,
                             self.entities [ entity_id ].pos_y,
                             self.entities [ entity_id ].pos_z )
        self.framework.let_ent_lock ( )
        if not ent_position:
            return -1
        distance = self.framework.utils.calculate_distance ( self.framework.utils.get_coordinates ( player ),
                                                             ent_position )
        bearing = self.framework.utils.calculate_bearings ( ( player.pos_x, player.pos_y ),
                                                            ( ent_position [ 0 ], ent_position [ 1 ] ) )
        self.framework.console.pm ( player, "{:.1f}m {} (height: {:.1f}m)".format ( distance,
                                                                                    bearing,
                                                                                    player.pos_z - ent_position [ 2 ] ) )
        #self.framework.console.pm ( player, "{}".format ( self.framework.utils.get_map_coordinates ( ent_position ) ) )
        return distance
            
    def show_inventory ( self, player ):
        msg = "showinventory " + str ( player )
        self.console ( msg )
        
    def sos ( self, msg_origin, msg_contents ):
        origin = self.get_player ( msg_origin )
        for key in self.players_info.keys ( ):
            if ( self.players_info [ key ].online == True and
                 key != origin.playerid ):
                helper = self.get_player ( key )
                bearings = self.calculate_bearings ( origin, helper )
                msg = 'pm %s "Go %.1fm in direction %d degrees (N is zero ) to help %s if you can!"'
                self.console ( msg % ( helper.name_sane,
                                       bearings [ 0 ],
                                       bearings [ 1 ],
                                       origin.name_sane ) )

    def spawn_player_stuff ( self,
                             playerid,
                             stuff ):
        msg = 'se ' + playerid + ' ' + str ( stuff )
        self.log.debug ( msg )
        self.console ( msg )

    def stop ( self ):
        self.shutdown = True
        
    def teleport ( self, player_info, where_to ):
        """
        The where_to argument expects a tuple with coordinates ( +E/-W, +N/-S, height ).
        """
        player = self.get_player ( player_info )
        if player == None:
            self.log.error ( "teleport received None from get_player." )
            return
        
        if player != None:
            msg = 'teleportplayer ' + str ( player.playerid ) + ' '
        else:
            msg = 'teleportplayer ' + str ( player_info ) + ' '
        if isinstance ( where_to, str ):
            msg += where_to
        elif isinstance ( where_to, tuple ):
            msg += str ( int ( where_to [ 0 ] ) ) + " " + \
                   str ( int ( where_to [ 2 ] ) ) + " " + \
                   str ( int ( where_to [ 1 ] ) )
        self.console ( msg )
        player.pos_x = where_to [ 0 ]
        player.pos_y = where_to [ 1 ]
        player.pos_z = where_to [ 2 ]

    def preteleport ( self, player_info, where_to ):
        """
        The where_to argument expects a tuple with coordinates ( +E/-W, +N/-S, height ).
        """
        player = self.get_player ( player_info )
        if player == None:
            self.log.error ( "teleport received None from get_player." )
            return
        
        if player != None:
            msg = 'teleportplayer ' + str ( player.playerid ) + ' '
        else:
            msg = 'teleportplayer ' + str ( player_info ) + ' '
        premsg = msg
        if isinstance ( where_to, tuple ):
            msg += str ( int ( where_to [ 0 ] ) ) + " " + \
                   str ( int ( where_to [ 2 ] ) + 1 ) + " " + \
                   str ( int ( where_to [ 1 ] ) )
            premsg += str ( int ( where_to [ 0 ] ) ) + " " + \
                      str ( int ( where_to [ 2 ] ) - 5000 ) + " " + \
                      str ( int ( where_to [ 1 ] ) )
        self.console ( premsg )
        time.sleep ( 3 )
        self.console ( msg )
        player.pos_x = where_to [ 0 ]
        player.pos_y = where_to [ 1 ]
        player.pos_z = where_to [ 2 ]

    def update_gt ( self, line_string ):
        now = time.time ( )
        new_gt = { }

        previous_day = self.game_server.day
        previous_hour = self.game_server.hour
        previous_minute = self.game_server.minute
        
        day_matcher = re.compile ( r'Day ([0-9]+), ([0-9]{2}):([0-9]{2})' )
        day_match = day_matcher.search ( line_string )
        if day_match:
            try:
                day    = int ( day_match.group ( 1 ) )
                hour   = int ( day_match.group ( 2 ) )
                minute = int ( day_match.group ( 3 ) )
            except IndexError as e:
                self.log.error ( "update_gt ( {:s} ): {:s}.".format (
                    str ( line_string ), str ( e ) ) )
                return
            
            self.game_server.time   = ( day, hour, minute )
            self.game_server.day    = day
            self.game_server.hour   = hour
            self.game_server.minute = minute

            if ( previous_day != self.game_server.day ):
                self.framework.game_events.day_changed ( previous_day )
            if ( previous_hour != self.game_server.hour ):
                self.framework.game_events.hour_changed ( previous_hour )

        self.game_server.gt = ( new_gt, now )
        
    def update_id ( self, id_fields ):
        self.latest_id_parse_call = time.time ( )

        playerid = int ( id_fields [ 0 ] )
        playername =     id_fields [ 1 ]
        pos_x  = float ( id_fields [ 2 ] )
        pos_y  = float ( id_fields [ 4 ] )
        pos_z  = float ( id_fields [ 3 ] )
        rot_x  = float ( id_fields [ 5 ] )
        rot_y  = float ( id_fields [ 7 ] )
        rot_z  = float ( id_fields [ 6 ] )
        remote   =       id_fields [ 8 ]
        health   = int ( id_fields [ 9 ] )
        deaths   = int ( id_fields [ 10 ] )
        zombies  = int ( id_fields [ 11 ] )
        players  = int ( id_fields [ 12 ] )
        score    = int ( id_fields [ 13 ] )
        level    = int ( id_fields [ 14 ] )
        steamid  = int ( id_fields [ 15 ] )
        ip       =       id_fields [ 16 ]
        ping     = int ( id_fields [ 17 ] )
        
        country = self.geoip.country_code_by_addr ( ip ) #todo: move this to a conn event

        self.player_info_update ( level = level,
                                  name = playername,
                                  online = True,
                                  playerid = playerid,
                                  pos_x = pos_x,
                                  pos_y = pos_y,
                                  pos_z = pos_z,
                                  health = health,
                                  ip = ip,
                                  deaths = deaths,
                                  zombies = zombies,
                                  players = players,
                                  score = score,
                                  steamid = steamid )

        pickle_file = open ( self.player_info_file, 'wb' )
        pickle.dump ( self.players_info, pickle_file, pickle.HIGHEST_PROTOCOL )
        now = time.time ( )
        if ( now - self.latest_player_db_backup > 24 * 3600 ):
            self.latest_player_db_backup = now
            backup_file_name = self.player_info_file + "_" + time.strftime ( "%Y-%m-%d_%Hh%M.pickle" )
            backup_file = open ( backup_file_name, 'wb' )
            pickle.dump ( self.players_info, backup_file, pickle.HIGHEST_PROTOCOL )

    def update_le ( self, matches ):
        le_id = int ( matches [ 0 ] )
        raw_type = matches [ 1 ]
        
        known_types = [
            'animalPig',
            'animalRabbit',
            'animalStag',
            'burntzombie',
            'car_Blue',
            'car_Orange',
            'car_Red',
            'car_White',
            'EntityPlayer',
            'EntitySupplyPlane',
            'fatzombie',
            'hornet',
            'sc_General',
            'spiderzombie',
            'zombie04',
            'zombie05',
            'zombie06',
            'zombie07',
            'zombiecrawler',
            'zombiedog',
            'zombieferal',
            'zombiegal01',
            'zombiegal02',
            'zombiegal03',
            'zombiegal04',
            ]
        le_type = None
        for known in known_types:
            if known in raw_type:
                le_type = known
                break
        if not le_type:
            self.log.warning ( "Unknown entity found: {}." . format ( matches [ 1 ] ) )
            le_type = matches [ 1 ]

        if ( le_type == "EntityPlayer" or
             le_type == 'EntitySupplyPlane' or
             le_type == "car_Blue" or
             le_type == "car_Orange" or
             le_type == "car_Red" or             
             le_type == "car_White" ):
            return
            
        pos_x  = float ( matches [ 2 ] )
        pos_y  = float ( matches [ 4 ] )
        pos_z  = float ( matches [ 3 ] )
        rot_x  = float ( matches [ 5 ] )
        rot_y  = float ( matches [ 7 ] )
        rot_z  = float ( matches [ 6 ] )
        lifetime = matches [ 8 ]
        remote = matches [ 9 ]
        dead = matches [ 10 ]
        health = int ( matches [ 11 ] )

        self.framework.get_ent_lock ( ) 
        if le_id in self.framework.server.entities.keys ( ):
            entity = self.framework.server.entities [ le_id ]
        else:
            entity = framework.entity_info ( )
        entity.entity_id = le_id
        entity.entity_type = le_type
        entity.pos_x = pos_x
        entity.pos_y = pos_y
        entity.pos_z = pos_z
        entity.rot_x = rot_x
        entity.rot_z = rot_z
        entity.lifetime = lifetime
        entity.remote = remote
        entity.dead = dead
        entity.health = health

        entity.timestamp = time.time ( )
        
        self.framework.server.entities [ le_id ] = entity
        self.framework.let_ent_lock ( ) 
        
    def update_mem ( self, line_string ):
        now =  time.time ( )
        new_mem_info = { } 
        time_matcher = re.compile ( r'Time: ([0-9]+.[0-9]+)m' )
        time_match = time_matcher.search ( line_string )
        if time_match:
            new_mem_info [ 'time' ] = time_match.group ( 1 )
        fps_matcher = re.compile ( r'FPS: ([0-9]+.[0-9]+)' )
        fps_match = fps_matcher.search ( line_string )
        if fps_match:
            new_mem_info [ 'fps' ] = fps_match.group ( 1 )
        heap_matcher = re.compile ( r'Heap: ([0-9]+.[0-9]+)MB' )
        heap_match = heap_matcher.search ( line_string )
        if heap_match:
            new_mem_info [ 'heap' ] = heap_match.group ( 1 )
        max_matcher = re.compile ( r'Max: ([0-9]+.[0-9]+)MB' )
        max_match = max_matcher.search ( line_string )
        if max_match:
            new_mem_info [ 'max' ] = max_match.group ( 1 )
        chunks_matcher = re.compile ( r'Chunks: ([0-9]+)' )
        chunks_match = chunks_matcher.search ( line_string )
        if chunks_match:
            new_mem_info [ 'chunks' ] = chunks_match.group ( 1 )
        cgo_matcher = re.compile ( r'CGO: ([0-9]+)' )
        cgo_match = cgo_matcher.search ( line_string )
        if cgo_match:
            new_mem_info [ 'cgo' ] = cgo_match.group ( 1 )
        players_matcher = re.compile ( r'Ply: ([0-9]+)' )
        players_match = players_matcher.search ( line_string )
        if players_match:
            new_mem_info [ 'players' ] = players_match.group ( 1 )
        zombies_matcher = re.compile ( r'Zom: ([0-9]+)' )
        zombies_match = zombies_matcher.search ( line_string )
        if zombies_match:
            new_mem_info [ 'zombies' ] = zombies_match.group ( 1 )
        entities_1_matcher = re.compile ( r'Ent: ([0-9]+)' )
        entities_1_match = entities_1_matcher.search ( line_string )
        if entities_1_match:
            new_mem_info [ 'entities_1' ] = entities_1_match.group ( 1 )
        entities_2_matcher = re.compile ( r'Ent: [0-9]+ \(([0-9]+)\)' )
        entities_2_match = entities_2_matcher.search ( line_string )
        if entities_2_match:
            new_mem_info [ 'entities_2' ] = entities_2_match.group ( 1 )
        items_matcher = re.compile ( r'Items: ([0-9]+)' )
        items_match = items_matcher.search ( line_string )
        if items_match:
            new_mem_info [ 'items' ] = items_match.group ( 1 )
            
        self.game_server.mem = ( new_mem_info, now )
        
    def update_players_pickle ( self ):
        import framework
        new_players_info = { }
        for key in self.players_info.keys ( ):
            player = self.get_player ( key )
            if player != None:
                new_player = None
                a_key = list ( self.players_info.keys ( ) ) [ 0 ]
                
                if self.players_info [ a_key ].__class__.__name__ == 'player_info_v1':
                    new_player = framework.player_info.player_info_v2 ( deaths = player.deaths,
                                                                        health = player.health,
                                                                        home = player.home,
                                                                        ip = player.ip,
                                                                        level = player.level,
                                                                        name = player.name,
                                                                        online = player.online,
                                                                        playerid = player.playerid,
                                                                        players = player.players,
                                                                        pos_x = player.pos_x,
                                                                        pos_y = player.pos_y,
                                                                        pos_z = player.pos_z,
                                                                        score = player.score,
                                                                        steamid = player.steamid,
                                                                        zombies = player.zombies )
                    new_player.home_invasion_beacon = player.home_invasion_beacon
                    new_player.home_invitees = player.home_invitees
                    new_player.language_preferred = player.language_preferred
                    new_player.languages_spoken = player.languages_spoken
                    new_player.map_limit_beacon = player.map_limit_beacon
                    new_player.name_sane = self.sanitize ( player.name )
                    new_player.attributes = player.attributes
                    # New attribute:
                    new_player.camp = None
                    
                if self.players_info [ a_key ].__class__.__name__ == 'player_info_v2':
                    new_player = framework.player_info.player_info_v3 ( deaths = player.deaths,
                                                                        health = player.health,
                                                                        home = player.home,
                                                                        ip = player.ip,
                                                                        level = player.level,
                                                                        name = player.name,
                                                                        online = player.online,
                                                                        playerid = player.playerid,
                                                                        players = player.players,
                                                                        pos_x = player.pos_x,
                                                                        pos_y = player.pos_y,
                                                                        pos_z = player.pos_z,
                                                                        score = player.score,
                                                                        steamid = player.steamid,
                                                                        zombies = player.zombies )
                    new_player.home_invasion_beacon = player.home_invasion_beacon
                    new_player.home_invitees = player.home_invitees
                    new_player.language_preferred = player.language_preferred
                    new_player.languages_spoken = player.languages_spoken
                    new_player.map_limit_beacon = player.map_limit_beacon
                    new_player.name_sane = self.sanitize ( player.name )
                    new_player.attributes = player.attributes
                    new_player.camp = player.camp
                    # new
                    new_player.online_time = 0
                    new_player.player_kills_explanations = [ ]

                if self.players_info [ a_key ].__class__.__name__ == 'player_info_v3':
                    new_player = framework.player_info.player_info_v4 ( deaths = player.deaths,
                                                                        health = player.health,
                                                                        home = player.home,
                                                                        ip = player.ip,
                                                                        level = player.level,
                                                                        name = player.name,
                                                                        online = player.online,
                                                                        playerid = player.playerid,
                                                                        players = player.players,
                                                                        pos_x = player.pos_x,
                                                                        pos_y = player.pos_y,
                                                                        pos_z = player.pos_z,
                                                                        score = player.score,
                                                                        steamid = player.steamid,
                                                                        zombies = player.zombies )
                    new_player.attributes = player.attributes
                    new_player.camp = player.camp
                    new_player.cash = player.cash
                    new_player.home_invasion_beacon = player.home_invasion_beacon
                    new_player.home_invitees = player.home_invitees
                    new_player.karma = player.karma
                    new_player.language_preferred = player.language_preferred
                    new_player.languages_spoken = player.languages_spoken
                    new_player.map_limit_beacon = player.map_limit_beacon
                    new_player.name_sane = self.sanitize ( player.name )
                    new_player.online_time = player.online_time
                    new_player.player_kills_explanations = player.player_kills_exaplanations
                    new_player.timestamp_latest_update = player.timestamp_latest_update

                    #new
                    new_player.accounted_zombies = player.zombies

                if self.players_info [ a_key ].__class__.__name__ == 'player_info_v4':
                    new_player = framework.player_info.player_info_v5 ( deaths = player.deaths,
                                                                        health = player.health,
                                                                        home = player.home,
                                                                        ip = player.ip,
                                                                        level = player.level,
                                                                        name = player.name,
                                                                        online = player.online,
                                                                        playerid = player.playerid,
                                                                        players = player.players,
                                                                        pos_x = player.pos_x,
                                                                        pos_y = player.pos_y,
                                                                        pos_z = player.pos_z,
                                                                        score = player.score,
                                                                        steamid = player.steamid,
                                                                        zombies = player.zombies )
                    new_player.accounted_zombies = player.zombies
                    new_player.attributes = player.attributes
                    new_player.camp = player.camp
                    new_player.cash = player.cash
                    new_player.home_invasion_beacon = player.home_invasion_beacon
                    new_player.home_invitees = player.home_invitees
                    new_player.karma = player.karma
                    new_player.language_preferred = player.language_preferred
                    new_player.languages_spoken = player.languages_spoken
                    new_player.map_limit_beacon = player.map_limit_beacon
                    new_player.name_sane = self.sanitize ( player.name )
                    new_player.online_time = player.online_time
                    new_player.player_kills_explanations = player.player_kills_exaplanations
                    new_player.timestamp_latest_update = player.timestamp_latest_update

                    # new
                    new_player.home_invasions = [ ]

                if new_player == None:
                    self.log.error ( "new_player == None!" )
                    self.log.info ( "self.players_info [ a_key ].__class__.__name__ = %s." %
                                    self.players_info.__class__.__name__ )
                    return
                new_players_info [ key ] = new_player

        self.log.info ( "Creating new player info file." )
        pickle_file = open ( self.player_info_file, 'wb' )
        pickle.dump ( new_players_info, pickle_file, pickle.HIGHEST_PROTOCOL )
        self.log.info ( "Resetting pointer." )
        self.players_info = new_players_info

    def wait_entities ( self ):
        for counter in range ( 100 ):
            if self.entities == { }:
                time.sleep ( self.framework.preferences.loop_wait / 10 )
                continue
            break

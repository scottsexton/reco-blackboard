#!/usr/bin/env python
import httplib
import json
import sys
import urllib


class BlackboardObject(object):
    """ An object that can be placed on the blackboard """
    def __init__(self, blackboard, *args, **kwargs):
        super(BlackboardObject, self).__init__(*args, **kwargs)
        self.blackboard = blackboard

    def register(self):
        self.blackboard.append(self)

    def resign(self):
        self.blackboard.remove(self)


class DependencyMixin(object):
    """ This mixin can be added to provide pub-sub features to an object """
    @property
    def dependents(self):
        default = []
        return getattr(self, '_dependents', default)

    def add_dependent(self, knowledge_source):
        if not hasattr(self, '_dependents'):
            self._dependents = []
        self._dependents.append(knowledge_source)

    def remove_dependent(self, knowledge_source):
        if self.dependents:
            self._dependents.remove(knowledge_source)

    def notify(self, response):
        if self.dependents:
            for knowledge_source in self.dependents:
                knowledge_source.be_notified(self, response)


class Blackboard(object):
    """ The blackboard serves as a shared state on the progress toward a solution to the problem """
    def __init__(self):
        self.pool = []
        self.affirmations = []
        self.solving = None

    def empty_pool(self):
        for rec in self.pool:
            rec.resign()

    def print_board(self):
        print '\n\n\n\n\n\n\n'
        print '- - - - - THE BLACKBOARD - - - - -'
        print '- Find a recommendation based on:'
        print '-',self.solving.recommendation.__str__()
        print '-'
        print '- Recommendation Pool:'
        for rec in self.pool:
            print '-',rec.__str__()
        print '-'
        print '- Assumptions and Assertions:'
        for aff in self.affirmations:
            if aff.is_retractable():
                print '- **** Assumption:',
            else:
                print '- **** Assertion:',
            print '%s,' % aff.recommendation.id,
            if aff.score:
                print "%s with score of %.2f" % (aff.reason, aff.score),
            else:
                print aff.reason,
            print ": made by",aff.knowledge_source
        print '- - - - - ************** - - - - -'
        print


class Recommendation(BlackboardObject, DependencyMixin):
    """ This class represents the individual songs """
    def __init__(self, knowledge_source, **json_data):
        super(Recommendation, self).__init__(knowledge_source.blackboard)
        self.knowledge_source = knowledge_source
        self.__dict__.update(json_data)
        self.id = "%s - %s" % (self.artist['name'], self.name)

    def register(self):
        self.blackboard.pool.append(self)

    def resign(self):
        self.blackboard.pool.remove(self)

    def __str__(self):
        tags = getattr(self, 'tags', None)
        if tags is not None:
            more = len(tags) - 3
            tags = tags[:3]
            tags.append(u'(%s more)...' % more)
        return "**** %s, listeners: %s, duration: %s, playcount: %s, tags: %s" % (self.id, getattr(self,'listeners',None), getattr(self,'duration',None), getattr(self,'playcount',None), tags)


class Assumption(BlackboardObject):
    """ This class represents a piece of knowledge accumulated as we look for a solution """
    def __init__(self, recommendation, knowledge_source, reason):
        super(Assumption, self).__init__(knowledge_source.blackboard)
        self.recommendation = recommendation
        self.knowledge_source = knowledge_source
        self.reason = reason
        self.score = None

    def is_retractable(self):
        return True

    def register(self):
        self.blackboard.affirmations.append(self)

    def resign(self):
        self.blackboard.affirmations.remove(self)


class Assertion(Assumption):
    """ An Assumption that represents a permenent state of affairs """
    def is_retractable(self):
        return False

    def resign(self):
        raise Exception("Assertions may not be retracted or resigned.")


class KnowledgeSource(object):
    """ A knowledge source acts upon some data to provide a song recommendation """
    API_KEY = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

    def __init__(self, blackboard):
        self.blackboard = blackboard
        self.thinking_about = None
        self.data_feed = None
        self.default_limit = 20
        self.params = {'api_key': API_KEY,
                       'autocorrect': 1,
                       'format': 'json'}

    def assure_unique(self, preserve=None):
        while True:
            if len(self.data_feed) == 0:
                return None
            # pop a unique recommendation off the data feed
            song = self.data_feed.pop()
            self.params['method'] = 'track.getInfo'
            self.params['artist'] = song['artist']['name']
            self.params['track'] = song['name']
            song_info = self._make_request()
            rec_new = Recommendation(self, **song_info['track'])
            if preserve is not None:
                setattr(rec_new, preserve, song[preserve])
            if not rec_new:
                return None
            considered_songs = [idea.recommendation.id for
                    idea in self.blackboard.affirmations if
                    idea.reason == 'Initial song' or
                    idea.reason == 'Disliked by user' or
                    idea.reason == 'Liked by user']
            considered_songs.extend([pool.id for pool in self.blackboard.pool])
            if rec_new.id not in considered_songs:
                return rec_new

    def be_notified(self, recommendation, response):
        if response.lower() == 'yes':
            affirm = Assertion(recommendation,
                self,
                'Liked by user')
            affirm.register()
            self.blackboard.solving = affirm
        else:
            affirm = Assertion(recommendation,
                self,
                'Disliked by user')
            affirm.register()
            if recommendation.knowledge_source == self:
                self.get_recommendations(
                   artist=self.blackboard.solving.recommendation.artist['name'],
                   track=self.blackboard.solving.recommendation.name)

    def _make_request(self):
        # connect to the API and return a result
        encoded_params = urllib.urlencode(self.params)
        conn = httplib.HTTPConnection('ws.audioscrobbler.com')
        conn.request('GET', '/2.0/?'+encoded_params)
        resp = conn.getresponse()
        if resp.status == 200:
            return json.loads(resp.read())
        else:
            raise Exception("An error occurred when communicating \
with the server: %s %s" % (resp.status, resp.reason))

    def __str__(self):
        return self.__class__.__name__


class InfoSource(KnowledgeSource):
    """ A KnowledgeSource that gets the complete info for a requested track """
    def get_info(self, artist, track):
        song = "%s - %s" % (artist, track)
        if not self.thinking_about == "%s - %s" % (artist, track):
            self.thinking_about = song
            self.params['method'] = 'track.getInfo'
            self.params['artist'] = artist
            self.params['track'] = track
            self.data_feed = self._make_request()
        info = Recommendation(self, **self.data_feed['track'])
        info.add_dependent(self)
        affirm = Assertion(info, self, 'Initial song')
        affirm.register()
        self.blackboard.solving = affirm
        return info

    def be_notified(self, *args):
        pass


class TagSource(KnowledgeSource):
    """ Choose the track with the closest number of tags in common with the original song """
    def tag_song(self, song):
        self.params['method'] = 'track.getTopTags'
        self.params['limit'] = 19
        self.params['artist'] = song.artist['name']
        self.params['track'] = song.name
        results = self._make_request()
        # The API will not obey the limit param here. Slice the result list.
        tag_list = results['toptags']['tag']
        if not isinstance(tag_list, list):
            tag_list = [tag_list]
        top_tags = [tag['name'] for tag in tag_list][:self.params['limit']]
        setattr(song, 'tags', top_tags)

    def _register_assumption(self, song):
        for assumption in self.blackboard.affirmations:
            if assumption.knowledge_source == self and assumption.is_retractable():
                if assumption.recommendation.id == song['reco'].id:
                    return
                else:
                    assumption.resign()
                    break
        assumption = Assumption(song['reco'], self, "Closest match on tags")
        assumption.score = song['score']
        assumption.register()
        song['reco'].add_dependent(self)

    def choose(self):
        best_tag_count = 0
        best_tag_match = None
        tags_to_match = getattr(self.blackboard.solving.recommendation, 'tags', None)
        if tags_to_match is None:
            self.tag_song(self.blackboard.solving.recommendation)
            tags_to_match = self.blackboard.solving.recommendation.tags
        for song in self.blackboard.pool:
            song_tags = getattr(song, 'tags', None)
            if song_tags is None:
                self.tag_song(song)
                song_tags = song.tags
            tag_match_count = 0
            for tag in tags_to_match:
                if tag in song_tags:
                    tag_match_count += 1
            if tag_match_count > best_tag_count:
                best_tag_count = tag_match_count
                best_tag_match = song
        score = (best_tag_count/float(len(tags_to_match))) * 100.0
        best_idea = {'score': score, 'reco': best_tag_match}
        self._register_assumption(best_idea)
        return best_idea

    def be_notified(self, recommendation, response):
        for assumption in self.blackboard.affirmations:
            if assumption.knowledge_source == self:
                assumption.resign()
                break

class SimilarTrackSource(KnowledgeSource):
    """ Put the top track of a number of similar artists into the pool """
    def get_recommendations(self, artist, track, count=1, **kwargs):
        if not self.thinking_about == artist:
            self.thinking_about = artist
            self.params['method'] = 'artist.getSimilar'
            self.params['limit'] = self.default_limit
            self.params['artist'] = artist
            similar_artists_feed = self._make_request()
            similar_artists = [a['name'] for a in
                    similar_artists_feed['similarartists']['artist']]
            self.params['method'] = 'artist.getTopTracks'
            self.params['limit'] = 1
            top_tracks = []
            info_source = InfoSource(self.blackboard)
            for similar_artist in similar_artists:
                self.params['artist'] = similar_artist
                results = self._make_request()
                try:
                    top_tracks.append(results['toptracks']['track'])
                except KeyError:
                    raise Exception("There was an error looking up top tracks \
for artists similar to %s" % artist)
            top_tracks.reverse()
            self.data_feed = top_tracks
        while count > 0:
            rec_toptrack = self.assure_unique()
            if rec_toptrack:
                rec_toptrack.register()
                rec_toptrack.add_dependent(self)
            count -= 1


class PlaycountSource(KnowledgeSource):
    """ Get one based on playcount """
    def __init__(self, *args, **kwargs):
        super(PlaycountSource, self).__init__(*args, **kwargs)
        self.strategies = self._init_strategies()
        self.try_this = None
        self.source_quality = None

    def _init_strategies(self):
        return {'more': ['more plays', 'a lot more plays'],
                'fewer': ['fewer plays', 'a lot fewer plays']}

    def _register_strategy(self, recommendation, score=None):
        for assumption in self.blackboard.affirmations:
            if assumption.knowledge_source == self and assumption.is_retractable():
                if assumption.recommendation.id == recommendation.id:
                    return None
                else:
                    assumption.resign()
                    break
        assumption = Assumption(recommendation, self, 'Try %s' % self.try_this)
        if score:
            assumption.score = score
        assumption.register()
        recommendation.add_dependent(self)

    def choose(self, *args, **kwargs):
        # Return None if we've exhausted our options
        if len(self.blackboard.pool) == 0:
            return None
        # Examine the pool and make a suggestion
        position = {'closest playcount':{'delta':sys.maxint,'reco':None,'score':0},
                'a lot more plays':{'delta':-sys.maxint-1,'reco':None,'score':0},
                'a lot fewer plays':{'delta':sys.maxint,'reco':None,'score':0},
                'more plays':{'delta':sys.maxint,'reco':None,'score':0},
                'fewer plays':{'delta':-sys.maxint-1,'reco':None,'score':0}}
        for song in self.blackboard.pool:
            delta_playcount =  int(getattr(song, 'playcount', 0)) - int(self.blackboard.solving.recommendation.playcount)
            diff_playcount = abs((float(delta_playcount)/float(self.blackboard.solving.recommendation.playcount)) * 100)
            if abs(delta_playcount) < abs(position['closest playcount']['delta']):
                # Are we displacing a current closest?
                if position['closest playcount']['delta'] > delta_playcount:
                    position['more plays']['delta'] = position['closest playcount']['delta']
                    position['more plays']['reco'] = position['closest playcount']['reco']
                    position['more plays']['score'] = position['closest playcount']['score']
                elif position['closest playcount']['delta'] < delta_playcount:
                    position['fewer plays']['delta'] = position['closest playcount']['delta']
                    position['fewer plays']['reco'] = position['closest playcount']['reco']
                    position['fewer plays']['score'] = position['closest playcount']['score']
                position['closest playcount']['delta'] = delta_playcount
                position['closest playcount']['reco'] = song
                position['closest playcount']['score'] = 100 - diff_playcount
            if delta_playcount > 0 and delta_playcount > position['a lot more plays']['delta']:
                position['a lot more plays']['delta'] = delta_playcount
                position['a lot more plays']['reco'] = song
                position['a lot more plays']['score'] = diff_playcount
            if delta_playcount < 0 and delta_playcount < position['a lot fewer plays']['delta']:
                position['a lot fewer plays']['delta'] = delta_playcount
                position['a lot fewer plays']['reco'] = song
                position['a lot fewer plays']['score'] = diff_playcount
            if delta_playcount > 0 and delta_playcount < position['more plays']['delta'] and delta_playcount > position['closest playcount']['delta']:
                position['more plays']['delta'] = delta_playcount
                position['more plays']['reco'] = song
                position['more plays']['score'] = 100 - diff_playcount
            if delta_playcount < 0 and delta_playcount > position['fewer plays']['delta'] and delta_playcount < position['closest playcount']['delta']:
                position['fewer plays']['delta'] = delta_playcount
                position['fewer plays']['reco'] = song
                position['fewer plays']['score'] = 100 - diff_playcount
        # Based on the Assumptions we've made so far, choose with that strategy
        if self.try_this is None:
            self.try_this = 'closest playcount'
        best_idea = self._priority_fallback(position)
        if self.source_quality == 'GOOD':
            best_idea['score'] *= 1.25
        elif self.source_quality == 'POOR':
            best_idea['score'] *= 0.75
        self._register_strategy(best_idea['reco'], score=best_idea['score'])
        return best_idea

    def _priority_fallback(self, position):
        # If we have nothing the strategy we want to try, fall back to its related strategy.
        best_idea = position[self.try_this]
        if best_idea['reco'] is None:
            next_best_idea = {
                    'a lot more plays': 'more plays',
                    'more plays': 'a lot more plays',
                    'a lot fewer plays': 'fewer plays',
                    'fewer plays': 'a lot fewer plays',
                    }
            best_idea = position[next_best_idea[self.try_this]]
            if best_idea['reco'] is None:
                # Fall back to just the closest playcount if all else fails.
                self.try_this = 'closest playcount'
                best_idea = position[self.try_this]
            else:
                self.try_this = next_best_idea[self.try_this]
        return best_idea

    def be_notified(self, recommendation, response):
        if response.lower() == 'yes':
            self.source_quality = 'GOOD'
            self.strategies = self._init_strategies()
        else:
            playcount_assumption = None
            for assumption in self.blackboard.affirmations:
                if assumption.knowledge_source == self:
                    playcount_assumption = assumption
                    assumption.resign()
                    break
            self.try_this = None
            if playcount_assumption is None or playcount_assumption.recommendation.playcount < self.blackboard.solving.recommendation.playcount:
                if len(self.strategies['more']) > 0:
                    self.try_this = self.strategies['more'].pop()
            else:
                if len(self.strategies['fewer']) > 0:
                    self.try_this = self.strategies['fewer'].pop()
            if self.try_this is None:
                print "INFO: The Playcount Source has tried all its strategies without success. Applying a penalty to its suggestions."
                self.source_quality = 'POOR'
                self.strategies = self._init_strategies()


class Controller(object):
    def __init__(self):
        self.blackboard = Blackboard()
        self.source_info = InfoSource(self.blackboard)
        self.source_similartracks = SimilarTrackSource(self.blackboard)
        self.source_playcount = PlaycountSource(self.blackboard)
        self.source_tags = TagSource(self.blackboard)

    def run(self):
        print "Ask me for a recommendation based on a track of your choosing:"
        artist = raw_input('artist: ')
        track = raw_input('track: ')
        print "Working..."
        self.source_info.get_info(artist, track)
        print '    ~ getting similar artists and songs...'
        self.source_similartracks.get_recommendations(artist=artist,
                                                  track=track,
                                                  count=4)
        print '    ~ evaluating...'
        while True:
            best_idea = self.recommend()
            self.blackboard.print_board()
            if not best_idea:
                print "Sorry, but there are no more recommendations to be had."
                break
            print 'Do you like "%s" by %s?' % (best_idea.name,
                    best_idea.artist['name'])
            print 'Check it out: %s' % best_idea.url
            response = raw_input('response (yes/No): ')
            if response.lower() == 'yes':
                print "Great! Would you like me to make another recommendation?"
                response = raw_input('response (yes/No): ')
                if response.lower() != 'yes':
                    print "Okay. Goodbye!"
                    break
                else:
                    artist = best_idea.artist['name']
                    track = best_idea.name
                    self.like(best_idea)
                    print '    ~ evaluating...'
            else:
                print "Okay, I'll find another recommendation."
                self.dislike(best_idea)
                print "Working..."

    def like(self, recommendation):
        recommendation.notify('yes')
        self.blackboard.empty_pool()
        print 'Working...'
        print '    ~ getting similar artists and songs...'
        self.source_similartracks.get_recommendations(artist=recommendation.artist['name'],
                                                  track=recommendation.name,
                                                  count=4)

    def dislike(self, recommendation):
        recommendation.resign()
        recommendation.notify('no')

    def recommend(self):
        if len(self.blackboard.pool) == 0:
            return None
        playcount_suggestion = self.source_playcount.choose()
        tagmatch_suggestion = self.source_tags.choose()
        if playcount_suggestion is not None and tagmatch_suggestion is not None:
            if playcount_suggestion['score'] >= tagmatch_suggestion['score']:
                return playcount_suggestion['reco']
            else:
                return tagmatch_suggestion['reco']
        elif playcount_suggestion is None:
            return tagmatch_suggestion['reco']
        else:
            return playcount_suggestion['reco']


if __name__ == '__main__':
    service = Controller()
    service.run()

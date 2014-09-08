from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.views.decorators.http import require_POST
from django.shortcuts import render
from django.conf import settings
from instagram.client import InstagramAPI
from django.core.urlresolvers import reverse

from collections import defaultdict

import logging
logger = logging.getLogger(__name__)

import datetime

import os
import json
import urllib
from PIL import Image
from cStringIO import StringIO
import requests

def get_api(token=None):
    if token:
        return InstagramAPI(access_token=token)
    return InstagramAPI(
            client_id = getattr(settings, 'INSTAGRAM_CLIENT_ID'),
            client_secret = getattr(settings, 'INSTAGRAM_CLIENT_SECRET'),
            redirect_uri = 'http://instagrid.bencardy.co.uk',
          )

def main(request):

    if 'code' in request.GET:
        api = get_api()
        token = api.exchange_code_for_access_token(request.GET['code'])[0]
        request.session['instagram_token'] = token
        return HttpResponseRedirect(request.path)

    user = None
    recents = []
    max_id = None

    if request.session.get('instagram_token', None):
        api = get_api(request.session.get('instagram_token'))
        user = api.user()
        logger.info('Viewed by %s' % str(user))
        recents = api.user_recent_media(count=30)[0]
        max_id = recents[-1].id

    return render(request, 'grid/base.html', {
        'user': user,
        'recents': recents,
        'max_id': max_id,
    })

def link(request):
    api = get_api()
    redirect_uri = api.get_authorize_login_url(scope=['basic'])
    return HttpResponseRedirect(redirect_uri)

def unlink(request):
    request.session['instagram_token'] = None
    return HttpResponseRedirect('/')

def get_recent_media(request):
    max_id = request.GET.get('max_id', None)
    token = request.session.get('instagram_token')
    api = get_api(request.session.get('instagram_token'))
    medias, others = api.user_recent_media(count=30, max_id=max_id)
    return HttpResponse(json.dumps({'urls': [x.get_standard_resolution_url() for x in medias], 'max_id': medias[-1].id}), mimetype='application/json')

@require_POST
def generate(request):
    api = get_api(request.session.get('instagram_token'))
    cols = int(request.POST['col_count'])
    rows = int(request.POST['row_count'])
    size = int(request.POST['size'])
    border = int(request.POST['border'])
    colour = request.POST['colour']

    image_width = (cols * size) + (border * (cols + 1))
    image_height = (rows * size) + (border * (rows + 1))
    
    background = (0, 0, 0)
    if colour == 'white':
        background = (255, 255, 255)

    base = Image.new('RGB', (image_width, image_height), background)

    media, _next = api.user_recent_media(count=(cols*rows))
    for num, m in enumerate(media):
        img_file = StringIO(urllib.urlopen(m.get_standard_resolution_url()).read())
        img = Image.open(img_file)
        img = img.resize((size, size), Image.ANTIALIAS)
        left = border + ((size + border) * (num % cols)) 
        top = border + ((size + border) * (num / cols))
        base.paste(img, (left, top))
    
    image_name = '%s.png' % api.user().id
    path = os.path.join(getattr(settings, 'MEDIA_ROOT'), image_name)
    base.save(path)

    logger.info('Generated for %s' % str(api.user()))

    return HttpResponse('%s%s' % (getattr(settings, 'MEDIA_URL'), image_name))


def stats(request):

    DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

    if request.session.get('instagram_token', None):
        api = get_api(request.session.get('instagram_token'))
    else:
        return HttpResponseRedirect(reverse('grid.views.main'))

    followers = {}
    new_followers, response = api.user_followed_by()
    for u in new_followers:
        followers[(u.id, u.username)] = 0
    while response:
        req = requests.get(response).json()
        response = None
        for u in req['data']:
            followers[(u['id'], u['username'])] = 0
        if req['pagination']:
            response = req['pagination']['next_url']

    images = []
    
    response = True
    while response:
        max_id = None
        if len(images):
            max_id = images[-1].id
        media, response = api.user_recent_media(count=100, max_id=max_id)
        images.extend(media)

    filters = defaultdict(int)
    like_counts = []
    likes = defaultdict(list)
    comment_counts = []
    comments = defaultdict(list)
    hours = dict((x, 0) for x in range(24))
    days = dict((x, [0]*24) for x in DAYS)

    dt1 = images[-1].created_time
    dt2 = datetime.datetime.now()
    start_month=dt1.month
    end_months=(dt2.year-dt1.year)*12 + dt2.month+1
    dates=[datetime.datetime(year=yr, month=mn, day=1) for (yr, mn) in (
          ((m - 1) / 12 + dt1.year, (m - 1) % 12 + 1) for m in range(start_month, end_months)
      )]

    dates = dict((x, 0) for x in dates)

    users = {}

    for image in images:
        filters[image.filter] = filters[image.filter] + 1
        like_counts.append((image, image.like_count))
        for user in image.likes:
            users[user.id] = user
            try:
                followers[(user.id, user.username)] = followers[(user.id, user.username)] + 1
            except KeyError:
                pass
            likes[user.id].append(image)
        comment_counts.append((image, image.comment_count))
        for comment in image.comments:
            user = comment.user
            users[user.id] = user
            comments[user.id].append(image)
        t = image.created_time
        m = datetime.datetime(year=t.year, month=t.month, day=1)
        dates[m] = dates[m] + 1
        days[DAYS[t.weekday()]][t.hour] = days[DAYS[t.weekday()]][t.hour] + 1
        hours[image.created_time.hour] = hours[image.created_time.hour] + 1

    days = sorted(days.items(), key=lambda x: DAYS.index(x[0]))
    #raise Http404(days)

    filters = sorted(filters.items(), key=lambda x: -x[1])
    dates = sorted(dates.items(), key=lambda x: x[0])
    hours = sorted(hours.items(), key=lambda x: x[0])
    like_counts.sort(key=lambda x: -x[1])
    comment_counts.sort(key=lambda x: -x[1])
    likes = [(users[x], len(y)) for x, y in sorted(likes.items(), key=lambda x: -len(x[1]))]
    comments = [(users[x], len(y)) for x, y in sorted(comments.items(), key=lambda x: -len(x[1]))]
    followers = sorted([(x[1], y) for x, y in followers.items()], key=lambda x: -x[1])

    return render(request, 'grid/stats.html', {
        'filters': filters,
        'followers': followers,
        'dates': dates,
        'hours': hours,
        'like_counts': like_counts[:5],
        'likes': likes[:5],
        'comments': comments[:5],
        'comment_counts': comment_counts[:5],
    })

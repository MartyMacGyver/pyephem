#!/usr/bin/env python
# -*- coding: utf-8 -*-

import glob, math, re, unittest
from datetime import datetime
from time import strptime
import ephem

# Read an ephemeris from the United States Naval Observatory, and
# confirm that PyEphem returns the same measurements to within one
# arcsecond of accuracy.

def interpret_observer(line):
    """Return the Observer represented by a line from a USNO file.
              Location:  W 84°24'36.0", N33°45'36.0",   322m
    """
    fields = line.split()
    observer = ephem.Observer()
    observer.long = ':'.join(re.findall(r'[0-9.]+', fields[2]))
    observer.lat = ':'.join(re.findall(r'[0-9.]+', fields[3]))
    if fields[1] == 'W':
        observer.long *= -1
    if fields[3].startswith('S'):
        observer.lat *= -1
    observer.elevation = float(fields[-1][:-1])
    observer.pressure = 0
    return observer

def parse(line):
    """Read the date, RA, and dec from a USNO data file line."""

    fields = re.split(r'   +', line)
    dt = datetime(*strptime(fields[0][:-2], "%Y %b %d %H:%M:%S")[0:6])
    date = ephem.Date(dt)
    ra = ephem.hours(fields[1].replace(' ', ':'))
    sign, mag = fields[2].split(None, 1)
    dec = ephem.degrees(sign + mag.replace(' ', ':'))
    return date, ra, dec

def is_near(n, m):
    """Raise an exception if two values are not within an arcsecond."""

    if abs(n - m) > ephem.arcsecond:
        raise AssertionError('the USNO asserts the value %s'
                             ' but PyEphem instead returns %s'
                             % (n, m))

class Trial(object):
    def select_body(self, name):
        if name == 'Deneb':
            return ephem.readdb('Deneb,f|D|A2,20:41:25.91|2.25,'
                                '45:16:49.22|1.6,1.33,2000')
        elif name == 'Antares':
            return ephem.readdb('Antares,f|D|M1,16:29:24.46|-11.4,'
                                '-26:25:55.21|-23.2,1.07,2000')
        elif hasattr(ephem, name):
            return getattr(ephem, name)()
        else:
            raise ValueError('USNO test: unknown body %r' % name)

    def examine_content(self):
        firstline = self.lines[0]
        name = firstline.strip()
        self.body = self.select_body(name)

    def run(self, content):
        self.content = content
        self.lines = content.split('\n')
        self.examine_content()
        for line in self.lines:
            if line.strip() and line[0].isdigit():
                self.check_line(line)

# Check an "Astrometric Positions" file.

class Astrometric_Trial(Trial):
    def check_line(self, line):
        date, ra, dec = parse(line)

        self.body.compute(date)
        is_near(ra, self.body.astrometric_ra)
        is_near(dec, self.body.astrometric_dec)

# Check an "Apparent Geocentric Positions" file.

class Apparent_Geocentric_Trial(Trial):
    def check_line(self, line):
        date, ra, dec = parse(line)

        self.body.compute(date)
        is_near(ra, self.body.apparent_ra)
        is_near(dec, self.body.apparent_dec)

        # The values we get should not depend on our epoch.

        self.body.compute(date, epoch=date)
        is_near(ra, self.body.apparent_ra)
        is_near(dec, self.body.apparent_dec)

        # Since we only provided the body with a date, and not an
        # Observer, the computation should have been geocentric, and
        # thus the "ra" and "dec" fields should have had the apparent
        # positions copied into them as well.

        assert self.body.apparent_ra == self.body.ra
        assert self.body.apparent_dec == self.body.dec

# Check an "Apparent Topocentric Positions" file.

class Apparent_Topocentric_Trial(Trial):
    def examine_content(self):
        Trial.examine_content(self)
        for line in self.lines:
            if 'Location:' in line:
                self.observer = interpret_observer(line.strip())

    def check_line(self, line):
        date, ra, dec = parse(line)
        self.observer.date = date
        self.body.compute(self.observer)
        is_near(ra, self.body.ra)
        is_near(dec, self.body.dec)

# Check a "Rise and Set for the * for *" file.

class Rise_Set_Trial(Trial):
    def examine_content(self):
        name, year = re.search(r'Rise and Set for (.*) for (\d+)',
                               self.content).groups()
        if name.startswith('the '):
            name = name[4:]
        self.body = self.select_body(name)
        self.year = int(year)

        longstr, latstr = re.search(r'Location: (.\d\d\d \d\d), (.\d\d \d\d)',
                                    self.content).groups()
        longstr = longstr.replace(' ', ':').replace('W', '-').strip('E')
        latstr = latstr.replace(' ', ':').replace('S', '-').strip('N')

        self.observer = o = ephem.Observer()
        o.lat = latstr
        o.long = longstr
        o.elevation = 0

        if isinstance(self.body, ephem.Sun):
            o.pressure = 0
            o.horizon = '-0:50' # per USNO instructions for sun

    def check_line(self, line):
        """Determine whether PyEphem rising times match those of the USNO.
        Lines from this data file look like:

               Jan.       Feb.       Mar.       Apr.       May    ...
        Day Rise  Set  Rise  Set  Rise  Set  Rise  Set  Rise  Set ...
             h m  h m   h m  h m   h m  h m   h m  h m   h m  h m ...
        01  0743 1740  0734 1808  0707 1834  0626 1858  0549 1921 ...
        02  0743 1741  0734 1809  0705 1835  0624 1859  0548 1922 ...
        """

        o = self.observer
        year = self.year
        body = self.body
        day = int(line[0:2])
        for month in [ int(m) for m in range(1,13) ]:
            offset = month * 11 - 7
            piece = line[offset : offset + 9]
            if not piece.strip():
                continue
            o.date = ephem.Date((year, month, day))
            o.next_rising(body)
            d = ephem.Date(o.date - 5 * ephem.hour)

            usno_field = piece[:4]
            hr, min = int(piece[:2]), int(piece[2:4])
            usno_minutes_into_day = hr * 60 + min

            hr, min, sec = d.tuple()[3:6]
            our_minutes_into_day = hr * 60 + min + sec / 60.

            difference = our_minutes_into_day - usno_minutes_into_day
            if difference > 1.:
                raise ValueError('On %s, the USNO and PyEphem'
                                 ' differ about the time of sunrise'
                                 ' by more than one minute' % d)

# The actual function that drives the test.

class Mixin(object):
    def test_usno(self):

        titles = {
            'Astrometric Positions': Astrometric_Trial,
            'Apparent Geocentric Positions': Apparent_Geocentric_Trial,
            'Apparent Topocentric Positions': Apparent_Topocentric_Trial,
            'Rise and Set for': Rise_Set_Trial,
            }

        content = open(self.path).read()
        for title in titles:
            if title in content:
                trial_class = titles[title]
                trial = trial_class()
                trial.run(content)
                return
        raise ValueError('Cannot find a test trial that recognizes %r'
                         % self.path)

#
# Auto-detect files
#

i = 1
for path in glob.glob('tests/usno/*.txt'):
    exec 'class T%d(unittest.TestCase, Mixin): path = %r' % (i, path)
    i += 1

if __name__ == '__main__':
    unittest.main()

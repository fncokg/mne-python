# -*- coding: utf-8 -*-
#
# License: BSD-3-Clause

from datetime import datetime
from glob import glob
from os.path import basename, join, splitext
from xml.etree.ElementTree import parse

import numpy as np

from ...utils import logger


def _read_events(input_fname, info):
    """Read events for the record.

    Parameters
    ----------
    input_fname : str
        The file path.
    info : dict
        Header info array.
    """
    n_samples = info['last_samps'][-1]
    mff_events, event_codes = _read_mff_events(input_fname, info['sfreq'])
    info['n_events'] = len(event_codes)
    info['event_codes'] = event_codes
    events = np.zeros([info['n_events'], info['n_segments'] * n_samples])
    for n, event in enumerate(event_codes):
        for i in mff_events[event]:
            events[n][i] = n + 1
    return events, info


def _read_mff_events(filename, sfreq):
    """Extract the events.

    Parameters
    ----------
    filename : str
        File path.
    sfreq : float
        The sampling frequency
    """
    orig = {}
    for xml_file in glob(join(filename, '*.xml')):
        xml_type = splitext(basename(xml_file))[0]
        orig[xml_type] = _parse_xml(xml_file)
    xml_files = orig.keys()
    xml_events = [x for x in xml_files if x[:7] == 'Events_']
    for item in orig['info']:
        if 'recordTime' in item:
            start_time = _ns2py_time(item['recordTime'])
            break
    markers = []
    code = []
    for xml in xml_events:
        for event in orig[xml][2:]:
            event_start = _ns2py_time(event['beginTime'])
            start = (event_start - start_time).total_seconds()
            if event['code'] not in code:
                code.append(event['code'])
            marker = {'name': event['code'],
                      'start': start,
                      'start_sample': int(np.fix(start * sfreq)),
                      'end': start + float(event['duration']) / 1e9,
                      'chan': None,
                      }
            markers.append(marker)
    events_tims = dict()
    for ev in code:
        trig_samp = list(c['start_sample'] for n,
                         c in enumerate(markers) if c['name'] == ev)
        events_tims.update({ev: trig_samp})
    return events_tims, code


def _parse_xml(xml_file):
    """Parse XML file."""
    xml = parse(xml_file)
    root = xml.getroot()
    return _xml2list(root)


def _xml2list(root):
    """Parse XML item."""
    output = []
    for element in root:

        if len(element) > 0:
            if element[0].tag != element[-1].tag:
                output.append(_xml2dict(element))
            else:
                output.append(_xml2list(element))

        elif element.text:
            text = element.text.strip()
            if text:
                tag = _ns(element.tag)
                output.append({tag: text})

    return output


def _ns(s):
    """Remove namespace, but only if there is a namespace to begin with."""
    if '}' in s:
        return '}'.join(s.split('}')[1:])
    else:
        return s


def _xml2dict(root):
    """Use functions instead of Class.

    remove namespace based on
    http://stackoverflow.com/questions/2148119
    """
    output = {}
    if root.items():
        output.update(dict(root.items()))

    for element in root:
        if len(element) > 0:
            if len(element) == 1 or element[0].tag != element[1].tag:
                one_dict = _xml2dict(element)
            else:
                one_dict = {_ns(element[0].tag): _xml2list(element)}

            if element.items():
                one_dict.update(dict(element.items()))
            output.update({_ns(element.tag): one_dict})

        elif element.items():
            output.update({_ns(element.tag): dict(element.items())})

        else:
            output.update({_ns(element.tag): element.text})
    return output


def _ns2py_time(nstime):
    """Parse times."""
    nsdate = nstime[0:10]
    nstime0 = nstime[11:26]
    nstime00 = nsdate + " " + nstime0
    pytime = datetime.strptime(nstime00, '%Y-%m-%d %H:%M:%S.%f')
    return pytime


def _combine_triggers(data, remapping=None):
    """Combine binary triggers."""
    new_trigger = np.zeros(data.shape[1])
    if data.astype(bool).sum(axis=0).max() > 1:  # ensure no overlaps
        logger.info('    Found multiple events at the same time '
                    'sample. Cannot create trigger channel.')
        return
    if remapping is None:
        remapping = np.arange(data) + 1
    for d, event_id in zip(data, remapping):
        idx = d.nonzero()
        if np.any(idx):
            new_trigger[idx] += event_id
    return new_trigger

def parse_ECI_events_from_xml(fname):
    """
    Parse Events recorded by EGI's ECI(Experiment Control Interface) to a `list` of events information.

    The information is usally generated by EPrime and saved in files like `*.mff/Events_ECI*.xml`.

    Parameters
    ----------
    fname : str
        The location of the `*.mff/Events_ECI*.xml` file.

    Returns
    ----------
    events : list[dict].
        Every `event` tag in the XML file is converted to a dict object in the list `events`. The `keys` tag is converted to a dict in which every raw `key` tag is parsed as a key value pair.
    """

    def parse_key(key):
        """
        Parse a `key` element to a key-value tuple.

        Parameters
        ----------
        key : Element


        Returns
        -------
        tuple
            (keyCode,data) tuple where data is converted accroding to the `dataType` attrib.
        """
        code = key.find("ns:keyCode", ns).text
        data = key.find("ns:data", ns)
        val = parse_key_type[data.get("dataType")](data.text)
        return code, val

    root = parse(fname).getroot()
    ns = {"ns": "http://www.egi.com/event_mff"}

    # The value of every sub-element in the `event` element is properly converted through this.
    parse_element = {
        """
        The original time format looks like "2021-12-11T11:50:58.962555+08:00"

        Note: In Python<3.7, `%z` CANNOT match timezone strings in format "±HH:MM"(only "±HHMM" is acceptable while in Python>=3.7 this is okay). Replace the final ":" first is out of compatibility.
        """
        "beginTime": lambda e: datetime.strptime(
            e.text[::-1].replace(":", "", 1)[::-1], "%Y-%m-%dT%H:%M:%S.%f%z"
        ),
        "duration": lambda e: int(e.text),
        "relativeBeginTime": lambda e: int(e.text),
        "segmentationEvent": lambda e: e.text == "true",
        "code": lambda e: str(e.text),
        "label": lambda e: str(e.text),
        "description": lambda e: str(e.text),
        "sourceDevice": lambda e: str(e.text),
        "keys": lambda e: dict([parse_key(key) for key in e.findall("ns:key", ns)]),
    }

    # Parse the key data to proper type.
    parse_key_type = {
        "short": np.int16,
        "long": np.int64,
        "string": str,
        "TEXT": str,
    }

    # Parse all event tags
    events = [
        {
            tag: parse_element[tag](element)
            for tag, element in map(lambda x: (_ns(x.tag), x), event)
        }
        for event in root.findall("ns:event", ns)
    ]
    return events
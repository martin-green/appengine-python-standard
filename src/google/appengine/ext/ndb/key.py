#!/usr/bin/env python
#
# Copyright 2007 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
















"""The Key class, and associated utilities.

A Key encapsulates the following pieces of information, which together
uniquely designate a (possible) entity in the App Engine datastore:

- an application id (a string)
- a namespace (a string)
- a list of one or more (kind, id) pairs where kind is a string and id
  is either a string or an integer.

The application id must always be part of the key, but since most
applications can only access their own entities, it defaults to the
current application id and you rarely need to worry about it.  It must
not be empty.

The namespace designates a top-level partition of the key space for a
particular application.  If you've never heard of namespaces, you can
safely ignore this feature.

Most of the action is in the (kind, id) pairs.  A key must have at
least one (kind, id) pair.  The last (kind, id) pair gives the kind
and the id of the entity that the key refers to, the others merely
specify a 'parent key'.

The kind is a string giving the name of the model class used to
represent the entity.  (In more traditional databases this would be
the table name.)  A model class is a Python class derived from
ndb.Model; see the documentation for ndb/model.py.  Only the class
name itself is used as the kind.  This means all your model classes
must be uniquely named within one application.  You can override this
on a per-class basis.

The id is either a string or an integer.  When the id is a string, the
application is in control of how it assigns ids: For example, if you
could use an email address as the id for Account entities.

To use integer ids, you must let the datastore choose a unique id for
an entity when it is first inserted into the datastore.  You can set
the id to None to represent the key for an entity that hasn't yet been
inserted into the datastore.  The final key (including the assigned
id) will be returned after the entity is successfully inserted into
the datastore.

A key for which the id of the last (kind, id) pair is set to None is
called an incomplete key.  Such keys can only be used to insert
entities into the datastore.

A key with exactly one (kind, id) pair is called a top level key or a
root key.  Top level keys are also used as entity groups, which play a
role in transaction management.

If there is more than one (kind, id) pair, all but the last pair
represent the 'ancestor path', also known as the key of the 'parent
entity'.

Other constraints:

- Kinds and string ids must not be empty and must be at most 500 bytes
  long (after UTF-8 encoding, if given as Python unicode objects).
  NOTE: This is defined as a module level constant _MAX_KEYPART_BYTES.

- Integer ids must be at least 1 and less than 2**63.

For more info about namespaces, see
http://code.google.com/appengine/docs/python/multitenancy/overview.html.
The namespace defaults to the 'default namespace' selected by the
namespace manager.  To explicitly select the empty namespace pass
namespace=''.
"""

import base64
import os

from google.appengine.api import cmp_compat
from google.appengine.api import datastore_errors
from google.appengine.api import datastore_types
from google.appengine.api import full_app_id
from google.appengine.api import namespace_manager
from google.appengine.ext.ndb import utils
import six
from six.moves import range

from google.appengine.datastore import entity_bytes_pb2 as entity_pb2

__all__ = ['Key']

_MAX_LONG = 2**63
_MAX_KEYPART_BYTES = 500




@cmp_compat.total_ordering_from_cmp
class Key(object):
  """An immutable datastore key.

  For flexibility and convenience, multiple constructor signatures are
  supported.

  The primary way to construct a key is using positional arguments:
  - Key(kind1, id1, kind2, id2, ...).

  This is shorthand for either of the following two longer forms:
  - Key(pairs=[(kind1, id1), (kind2, id2), ...])
  - Key(flat=[kind1, id1, kind2, id2, ...])

  Either of the above constructor forms can additionally pass in another
  key using parent=<key>.  The (kind, id) pairs of the parent key are
  inserted before the (kind, id) pairs passed explicitly.

  You can also construct a Key from a 'url-safe' encoded string:
  - Key(urlsafe=<string>)

  For esoteric purposes the following constructors exist:
  - Key(reference=<reference>) -- passing in a low-level Reference object
  - Key(serialized=<string>) -- passing in a serialized low-level Reference
  - Key(<dict>) -- for unpickling, the same as Key(**<dict>)

  The 'url-safe' string is really a websafe-base64-encoded serialized
  Reference, but it's best to think of it as just an opaque unique
  string.

  Additional constructor keyword arguments:
  - app=<string> -- specify the application id
  - namespace=<string> -- specify the namespace

  If a Reference is passed (using one of reference, serialized or
  urlsafe), the args and namespace keywords must match what is already
  present in the Reference (after decoding if necessary).  The parent
  keyword cannot be combined with a Reference in any form.


  Keys are immutable, which means that a Key object cannot be modified
  once it has been created.  This is enforced by the implementation as
  well as Python allows.

  For access to the contents of a key, the following methods and
  operations are supported:

  - repr(key), str(key) -- return a string representation resembling
    the shortest constructor form, omitting the app and namespace
    unless they differ from the default value.

  - key1 == key2, key1 != key2 -- comparison for equality between Keys.

  - hash(key) -- a hash value sufficient for storing Keys in a dict.

  - key.pairs() -- a tuple of (kind, id) pairs.

  - key.flat() -- a tuple of flattened kind and id values, i.e.
    (kind1, id1, kind2, id2, ...).

  - key.app() -- the application id.

  - key.id() -- the string or integer id in the last (kind, id) pair,
    or None if the key is incomplete.

  - key.string_id() -- the string id in the last (kind, id) pair,
    or None if the key has an integer id or is incomplete.

  - key.integer_id() -- the integer id in the last (kind, id) pair,
    or None if the key has a string id or is incomplete.

  - key.namespace() -- the namespace.

  - key.kind() -- a shortcut for key.pairs()[-1][0].

  - key.parent() -- a Key constructed from all but the last (kind, id)
    pairs.

  - key.urlsafe() -- a websafe-base64-encoded serialized Reference.

  - key.serialized() -- a serialized Reference.

  - key.reference() -- a Reference object.  The caller promises not to
    mutate it.

  Keys also support interaction with the datastore; these methods are
  the only ones that engage in any kind of I/O activity.  For Future
  objects, see the document for ndb/tasklets.py.

  - key.get() -- return the entity for the Key.

  - key.get_async() -- return a Future whose eventual result is
    the entity for the Key.

  - key.delete() -- delete the entity for the Key.

  - key.delete_async() -- asynchronously delete the entity for the Key.

  Keys may be pickled.

  Subclassing Key is best avoided; it would be hard to get right.
  """

  __slots__ = ['__reference', '__pairs', '__app', '__namespace']

  def __new__(cls, *_args, **kwargs):
    """Constructor.  See the class docstring for arguments."""
    if _args:
      if len(_args) == 1 and isinstance(_args[0], dict):
        if kwargs:
          raise TypeError('Key() takes no keyword arguments when a dict is the '
                          'the first and only non-keyword argument (for '
                          'unpickling).')
        kwargs = _args[0]
      else:
        if 'flat' in kwargs:
          raise TypeError('Key() with positional arguments '
                          'cannot accept flat as a keyword argument.')
        kwargs['flat'] = _args


    if int(os.environ.get('NDB_PY2_UNPICKLE_COMPAT', '0')):
      kwargs = {six.ensure_str(k): v for (k, v) in kwargs.items()}

    self = super(Key, cls).__new__(cls)



    if 'reference' in kwargs or 'serialized' in kwargs or 'urlsafe' in kwargs:
      (self.__reference,
       self.__pairs,
       self.__app,
       self.__namespace) = self._parse_from_ref(cls, **kwargs)
    elif 'pairs' in kwargs or 'flat' in kwargs:
      self.__reference = None
      (self.__pairs,
       self.__app,
       self.__namespace) = self._parse_from_args(**kwargs)
    else:
      raise TypeError('Key() cannot create a Key instance without arguments.')
    return self

  @staticmethod
  def _parse_from_args(pairs=None, flat=None, app=None, namespace=None,
                       parent=None):
    if flat:
      if pairs is not None:
        raise TypeError('Key() cannot accept both flat and pairs arguments.')
      if len(flat) % 2:
        raise ValueError('Key() must have an even number of positional '
                         'arguments.')
      pairs = [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
    else:
      pairs = list(pairs)
    if not pairs:
      raise TypeError('Key must consist of at least one pair.')
    for i, (kind, id) in enumerate(pairs):
      if isinstance(id, six.text_type):
        id = six.ensure_binary(id)
      elif id is None:
        if i + 1 < len(pairs):
          raise datastore_errors.BadArgumentError(
              'Incomplete Key entry must be last')
      else:
        if not isinstance(id, six.integer_types + (six.binary_type,)):
          raise TypeError('Key id must be a string or a number; received %r' %
                          id)
      if isinstance(kind, type):
        kind = kind._get_kind()
      if isinstance(kind, six.text_type):
        kind = six.ensure_binary(kind)
      if not isinstance(kind, six.binary_type):
        raise TypeError(
            'Key kind must be a string or Model class; received %r' % kind)
      if not id:
        id = None
      pairs[i] = (kind, id)
    if parent is not None:
      if not isinstance(parent, Key):
        raise datastore_errors.BadValueError(
            'Expected Key instance, got %r' % parent)
      if not parent.id():
        raise datastore_errors.BadArgumentError(
            'Parent cannot have incomplete key')
      pairs[:0] = parent.__pairs
      if app:
        if app != parent.app():
          raise ValueError('Cannot specify a different app %r '
                           'than the parent app %r' %
                           (app, parent.app()))
      else:
        app = parent.__app
      if namespace is not None:
        if namespace != parent.namespace():
          raise ValueError('Cannot specify a different namespace %r '
                           'than the parent namespace %r' %
                           (namespace, parent.namespace()))
      else:
        namespace = parent.__namespace
    if not app:
      app = _DefaultAppId()
    if namespace is None:
      namespace = namespace_manager.get_namespace()



    app = six.ensure_binary(app)
    namespace = six.ensure_binary(namespace)

    return tuple(pairs), app, namespace

  @staticmethod
  def _parse_from_ref(cls, pairs=None, flat=None,
                      reference=None, serialized=None, urlsafe=None,
                      app=None, namespace=None, parent=None):
    """Construct a Reference; the signature is the same as for Key."""
    if cls is not Key:
      raise TypeError('Cannot construct Key reference on non-Key class; '
                      'received %r' % cls)
    if (bool(pairs) + bool(flat) + bool(reference) + bool(serialized) +
        bool(urlsafe) + bool(parent)) != 1:
      raise TypeError('Cannot construct Key reference from incompatible '
                      'keyword arguments.')
    if urlsafe:
      serialized = _DecodeUrlSafe(urlsafe)
    if serialized:
      reference = _ReferenceFromSerialized(serialized)
    if reference:
      reference = _ReferenceFromReference(reference)
    pairs = []
    elem = None
    path = reference.path
    for elem in path.element:
      kind = six.ensure_binary(elem.type)
      if elem.HasField('id'):
        id_or_name = elem.id
      else:
        id_or_name = six.ensure_binary(elem.name)
      if not id_or_name:
        id_or_name = None
      tup = (kind, id_or_name)
      pairs.append(tup)
    if elem is None:
      raise RuntimeError('Key reference has no path or elements (%r, %r, %r).'
                         % (urlsafe, serialized, str(reference)))




    ref_app = reference.app
    if app is not None:
      if app != ref_app:
        raise RuntimeError('Key reference constructed uses a different app %r '
                           'than the one specified %r' %
                           (ref_app, app))
    ref_namespace = reference.name_space
    if namespace is not None:
      if namespace != ref_namespace:
        raise RuntimeError('Key reference constructed uses a different '
                           'namespace %r than the one specified %r' %
                           (ref_namespace, namespace))



    ref_app = six.ensure_binary(ref_app)
    ref_namespace = six.ensure_binary(ref_namespace)

    return (reference, tuple(pairs), ref_app, ref_namespace)

  def _bytes2str(self, val):
    if isinstance(val, bytes):
      val = six.ensure_str(val)
    return val

  def __repr__(self):
    """String representation, used by str() and repr().

    We produce a short string that conveys all relevant information,
    suppressing app and namespace when they are equal to the default.
    """

    args = []
    for item in self.flat():
      if not item:
        args.append('None')
      elif isinstance(item, six.string_types):
        args.append(repr(item))
      else:
        args.append(str(item))
    if self.app() != _DefaultAppId():
      args.append('app=%r' % self.app())
    if self.namespace() != namespace_manager.get_namespace():
      args.append('namespace=%r' % self.namespace())
    return 'Key(%s)' % ', '.join(args)

  __str__ = __repr__

  def __hash__(self):
    """Hash value, for use in dict lookups."""




    return hash(tuple(self.pairs()))

  def __eq__(self, other):
    """Equality comparison operation."""


    if not isinstance(other, Key):
      return NotImplemented
    return (self.__pairs == other.__pairs and
            self.__app == other.__app and
            self.__namespace == other.__namespace)

  def __ne__(self, other):
    """The opposite of __eq__."""
    if not isinstance(other, Key):
      return NotImplemented
    return not self.__eq__(other)

  def __cmp__(self, other):

    if not isinstance(other, Key):
      return NotImplemented


    tuple_1 = (
        self.__app,
        self.__namespace,
        _ConvertPairsForComparison(self.__pairs))
    tuple_2 = (
        other.__app,
        other.__namespace,
        _ConvertPairsForComparison(other.__pairs))

    return cmp_compat.cmp(tuple_1, tuple_2)

  def __getstate__(self):
    """Private API used for pickling."""


    return ({'pairs': self.__pairs,
             'app': self.__app,
             'namespace': self.__namespace},)

  def __setstate__(self, state):
    """Private API used for pickling."""
    if len(state) != 1:
      raise TypeError('Invalid state length, expected 1; received %i' %
                      len(state))
    kwargs = state[0]
    if not isinstance(kwargs, dict):
      raise TypeError('Key accepts a dict of keyword arguments as state; '
                      'received %r' % kwargs)
    kwargs = {six.ensure_text(k): v for k, v in kwargs.items()}
    self.__reference = None
    (self.__pairs, self.__app, self.__namespace) = self._parse_from_args(
        pairs=tuple(kwargs['pairs']),
        app=kwargs['app'],
        namespace=kwargs['namespace'])

  def __getnewargs__(self):
    """Private API used for pickling."""
    return ({'pairs': self.__pairs,
             'app': self.__app,
             'namespace': self.__namespace},)

  def parent(self):
    """Return a Key constructed from all but the last (kind, id) pairs.

    If there is only one (kind, id) pair, return None.
    """
    pairs = self.__pairs
    if len(pairs) <= 1:
      return None
    return Key(pairs=pairs[:-1], app=self.__app, namespace=self.__namespace)

  def root(self):
    """Return the root key.  This is either self or the highest parent."""
    pairs = self.__pairs
    if len(pairs) <= 1:
      return self
    return Key(pairs=pairs[:1], app=self.__app, namespace=self.__namespace)

  def namespace(self):
    """Return the namespace."""
    return self._bytes2str(self.__namespace)

  def app(self):
    """Return the application id."""
    return self._bytes2str(self.__app)

  def id(self):
    """Return the string or integer id in the last (kind, id) pair, if any.

    Returns:
      A string or integer id, or None if the key is incomplete.
    """
    return self._bytes2str(self.__pairs[-1][1])

  def string_id(self):
    """Return the string id in the last (kind, id) pair, if any.

    Returns:
      A string id, or None if the key has an integer id or is incomplete.
    """
    id = self.id()
    if not isinstance(id, (str, bytes)):
      id = None
    return id

  def integer_id(self):
    """Return the integer id in the last (kind, id) pair, if any.

    Returns:
      An integer id, or None if the key has a string id or is incomplete.
    """
    id = self.id()
    if not isinstance(id, six.integer_types):
      id = None
    return id

  def pairs(self):
    """Return a tuple of (kind, id) pairs."""
    return tuple((self._bytes2str(p[0]), self._bytes2str(p[1]))
                 for p in self.__pairs)

  def flat(self):
    """Return a tuple of alternating kind and id values."""
    flat = []
    for kind, ID in self.pairs():
      flat.append(kind)
      flat.append(ID)
    return tuple(flat)

  def kind(self):
    """Return the kind of the entity referenced.

    This is the kind from the last (kind, id) pair.
    """
    return self._bytes2str(self.__pairs[-1][0])

  def reference(self):
    """Return the Reference object for this Key.

    This is a entity_pb2.Reference instance -- a protocol buffer class
    used by the lower-level API to the datastore.

    NOTE: The caller should not mutate the return value.
    """
    if self.__reference is None:
      self.__reference = _ConstructReference(self.__class__,
                                             pairs=self.__pairs,
                                             app=self.__app,
                                             namespace=self.__namespace)
    return self.__reference

  def serialized(self):
    """Return a serialized Reference object for this Key."""
    return self.reference().SerializeToString()

  def urlsafe(self):
    """Return a url-safe string encoding this Key's Reference.

    This string is compatible with other APIs and languages and with
    the strings used to represent Keys in GQL and in the App Engine
    Admin Console.
    """

    urlsafe = base64.b64encode(self.reference().SerializeToString())
    return urlsafe.rstrip(b'=').replace(b'+', b'-').replace(b'/', b'_').decode()




  def get(self, **ctx_options):
    """Synchronously get the entity for this Key.

    Return None if there is no such entity.
    """
    return self.get_async(**ctx_options).get_result()

  def get_async(self, **ctx_options):
    """Return a Future whose result is the entity for this Key.

    If no such entity exists, a Future is still returned, and the
    Future's eventual return result be None.
    """
    from google.appengine.ext.ndb import model, tasklets
    ctx = tasklets.get_context()
    cls = model.Model._kind_map.get(self.kind())
    if cls:
      cls._pre_get_hook(self)
    fut = ctx.get(self, **ctx_options)
    if cls:
      post_hook = cls._post_get_hook
      if not cls._is_default_hook(model.Model._default_post_get_hook,
                                  post_hook):
        fut.add_immediate_callback(post_hook, self, fut)
    return fut

  def delete(self, **ctx_options):
    """Synchronously delete the entity for this Key.

    This is a no-op if no such entity exists.
    """
    return self.delete_async(**ctx_options).get_result()

  def delete_async(self, **ctx_options):
    """Schedule deletion of the entity for this Key.

    This returns a Future, whose result becomes available once the
    deletion is complete.  If no such entity exists, a Future is still
    returned.  In all cases the Future's result is None (i.e. there is
    no way to tell whether the entity existed or not).
    """
    from google.appengine.ext.ndb import tasklets, model
    ctx = tasklets.get_context()
    cls = model.Model._kind_map.get(self.kind())
    if cls:
      cls._pre_delete_hook(self)
    fut = ctx.delete(self, **ctx_options)
    if cls:
      post_hook = cls._post_delete_hook
      if not cls._is_default_hook(model.Model._default_post_delete_hook,
                                  post_hook):
        fut.add_immediate_callback(post_hook, self, fut)
    return fut

  @classmethod
  def from_old_key(cls, old_key):
    return cls(urlsafe=str(old_key))

  def to_old_key(self):
    return datastore_types.Key(encoded=self.urlsafe())





@utils.positional(1)
def _ConstructReference(cls, pairs=None, flat=None,
                        reference=None, serialized=None, urlsafe=None,
                        app=None, namespace=None, parent=None):
  """Construct a Reference; the signature is the same as for Key."""
  if cls is not Key:
    raise TypeError('Cannot construct Key reference on non-Key class; '
                    'received %r' % cls)
  if (bool(pairs) + bool(flat) + bool(reference) + bool(serialized) +
      bool(urlsafe)) != 1:
    raise TypeError('Cannot construct Key reference from incompatible keyword '
                    'arguments.')
  if flat or pairs:
    if flat:
      if len(flat) % 2:
        raise TypeError('_ConstructReference() must have an even number of '
                        'positional arguments.')
      pairs = [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
    elif parent is not None:
      pairs = list(pairs)
    if not pairs:
      raise TypeError('Key references must consist of at least one pair.')
    if parent is not None:
      if not isinstance(parent, Key):
        raise datastore_errors.BadValueError(
            'Expected Key instance, got %r' % parent)
      pairs[:0] = parent.pairs()
      if app:
        if app != parent.app():
          raise ValueError('Cannot specify a different app %r '
                           'than the parent app %r' %
                           (app, parent.app()))
      else:
        app = parent.app()
      if namespace is not None:
        if namespace != parent.namespace():
          raise ValueError('Cannot specify a different namespace %r '
                           'than the parent namespace %r' %
                           (namespace, parent.namespace()))
      else:
        namespace = parent.namespace()
    reference = _ReferenceFromPairs(pairs, app=app, namespace=namespace)
  else:
    if parent is not None:
      raise TypeError('Key reference cannot be constructed when the parent '
                      'argument is combined with either reference, serialized '
                      'or urlsafe arguments.')
    if urlsafe:
      serialized = _DecodeUrlSafe(urlsafe)
    if serialized:
      reference = _ReferenceFromSerialized(serialized)
    if not reference.path().element_size():
      raise RuntimeError('Key reference has no path or elements (%r, %r, %r).'
                         % (urlsafe, serialized, str(reference)))

    if not serialized:
      reference = _ReferenceFromReference(reference)



    if app is not None:
      ref_app = reference.app()
      if app != ref_app:
        raise RuntimeError('Key reference constructed uses a different app %r '
                           'than the one specified %r' %
                           (ref_app, app))
    if namespace is not None:
      ref_namespace = reference.name_space()
      if namespace != ref_namespace:
        raise RuntimeError('Key reference constructed uses a different '
                           'namespace %r than the one specified %r' %
                           (ref_namespace, namespace))
  return reference


def _ReferenceFromPairs(pairs, reference=None, app=None, namespace=None):
  """Construct a Reference from a list of pairs.

  If a Reference is passed in as the second argument, it is modified
  in place.  The app and namespace are set from the corresponding
  keyword arguments, with the customary defaults.
  """
  if reference is None:
    reference = entity_pb2.Reference()
  reference.path.SetInParent()
  path = reference.path
  last = False
  for kind, idorname in pairs:
    if last:
      raise datastore_errors.BadArgumentError(
          'Incomplete Key entry must be last')
    t = type(kind)
    if t is six.binary_type:
      pass
    elif t is six.text_type:
      kind = six.ensure_binary(kind)
    else:
      if issubclass(t, type):

        from google.appengine.ext.ndb.model import Model
        modelclass = kind
        if not issubclass(modelclass, Model):
          raise TypeError('Key kind must be either a string or subclass of '
                          'Model; received %r' % modelclass)
        kind = modelclass._get_kind()
        t = type(kind)
      if t is six.binary_type:
        pass
      elif t is six.text_type:
        kind = six.ensure_binary(kind)
      elif issubclass(t, six.binary_type):
        pass
      elif issubclass(t, six.text_type):
        kind = six.ensure_binary(kind)
      else:
        raise TypeError('Key kind must be either a string or subclass of Model;'
                        ' received %r' % kind)

    if not (1 <= len(kind) <= _MAX_KEYPART_BYTES):
      raise ValueError('Key kind string must be a non-empty string up to %i'
                       'bytes; received %s' %
                       (_MAX_KEYPART_BYTES, kind))
    elem = path.element.add()
    elem.type = kind
    t = type(idorname)
    if t is int or t is int:

      if not (1 <= idorname < _MAX_LONG):
        raise ValueError('Key id number is too long; received %i' % idorname)
      elem.id = idorname
    elif t is str:

      if not (1 <= len(idorname) <= _MAX_KEYPART_BYTES):
        raise ValueError('Key name strings must be non-empty strings up to %i '
                         'bytes; received %s' %
                         (_MAX_KEYPART_BYTES, idorname))
      elem.name = idorname
    elif t is six.text_type:
      idorname = idorname.encode('utf8')

      if not (1 <= len(idorname) <= _MAX_KEYPART_BYTES):
        raise ValueError('Key name unicode strings must be non-empty strings up'
                         ' to %i bytes; received %s' %
                         (_MAX_KEYPART_BYTES, idorname))
      elem.name = idorname
    elif idorname is None:
      last = True
    elif issubclass(t, six.integer_types):

      if not (1 <= idorname < _MAX_LONG):
        raise ValueError('Key id number is too long; received %i' % idorname)
      elem.id = idorname
    elif issubclass(t, six.string_types) or t is six.binary_type:
      if issubclass(t, six.text_type):
        idorname = idorname.encode('utf8')

      if not (1 <= len(idorname) <= _MAX_KEYPART_BYTES):
        raise ValueError('Key name strings must be non-empty strings up to %i '
                         'bytes; received %s' % (_MAX_KEYPART_BYTES, idorname))
      elem.name = idorname
    else:
      raise TypeError('id must be either a numeric id or a string name; '
                      'received %r' % idorname)

  if not app:
    app = _DefaultAppId()

  reference.app = app

  if namespace is None:
    namespace = namespace_manager.get_namespace()

  if namespace:
    reference.name_space = namespace
  return reference


def _ReferenceFromReference(reference):
  """Copy a Reference."""
  new_reference = entity_pb2.Reference()
  new_reference.CopyFrom(reference)
  return new_reference


def _ReferenceFromSerialized(serialized):
  """Construct a Reference from a serialized Reference."""
  if not isinstance(serialized, (six.text_type, six.binary_type)):
    raise TypeError('serialized must be a string; received %r' % serialized)
  elif isinstance(serialized, six.text_type):
    serialized = serialized.encode('utf8')
  return entity_pb2.Reference.FromString(serialized)


def _DecodeUrlSafe(urlsafe):
  """Decode a url-safe base64-encoded string.

  This returns the decoded string.
  """
  if not isinstance(urlsafe, (six.text_type, six.binary_type)):
    raise TypeError('urlsafe must be a string; received %r' % urlsafe)
  if isinstance(urlsafe, six.text_type):
    urlsafe = urlsafe.encode('utf8')
  mod = len(urlsafe) % 4
  if mod:
    urlsafe += b'=' * (4 - mod)

  return base64.b64decode(urlsafe.replace(b'-', b'+').replace(b'_', b'/'))


def _DefaultAppId():
  """Return the default application id.

  This is taken from environment variables.
  """
  return full_app_id.get()


def _ConvertPairsForComparison(pairs):
  """Converts Key pairs to a format that enables consistent comparison.

  Here's a nasty one. Due to the tighter constraints on what can be compared
  in PY3, we can't compare Keys tuples directly, as they can contain a mix of
  strings and integers. The PY2 behavior in such cases seems to be that in
  cases of differing types, comparisons are determined via the type name
  itself.

  Now the nasty part. While this could be addressed by something along the
  lines of...

    cmp(str(type(x)), str(type(y)))

  ...in PY2, this results in 'int' < 'str'. But in PY3, this results in
  'bytes' < 'int', which produces a different sorted ordering of said Keys. In
  the interest of minimizing breakage in existing code, I implemented this
  method to maintain the PY2 sort ordering for Keys. Comparing mixed items in
  PY2 now results in 'int' < 'unicode', and PY3 results in 'int' < 'str'.

  Args:
    pairs: A tuple of tuples, corresponding to the (kind, id) pairs of a Key.

  Returns:
    A tuple of tuples, converted for consistent comparison.
  """
  conv = lambda x: six.ensure_text(x) if isinstance(x, six.binary_type) else x
  return tuple((conv(i), conv(j)) for i, j in pairs)

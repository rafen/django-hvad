import django
from django.apps import apps
from django.db import models
if django.VERSION >= (1, 8):
    from django.db.models.expressions import Col
else:
    from django.db.models.sql.datastructures import Col
from django.db.models.fields.related import ForeignObject
from django.utils.functional import cached_property
from hvad.utils import minimumDjangoVersion

#===============================================================================
# Field for language joins
#===============================================================================

class RawConstraint(object):
    def __init__(self, sql, aliases):
        self.sql = sql
        self.aliases = aliases

    def as_sql(self, qn, connection):
        aliases = tuple(qn(alias) for alias in self.aliases)
        return (self.sql % aliases, [])

class BetterTranslationsField(object):
    def __init__(self, translation_fallbacks, master):
        # Filter out duplicates, while preserving order
        self._fallbacks = []
        self._master = master
        seen = set()
        for lang in translation_fallbacks:
            if lang not in seen:
                seen.add(lang)
                self._fallbacks.append(lang)

    def get_extra_restriction(self, where_class, alias, related_alias):
        langcase = ('(CASE %s.language_code ' +
                    ' '.join('WHEN \'%s\' THEN %d' % (lang, i)
                             for i, lang in enumerate(self._fallbacks)) +
                    ' ELSE %d END)' % len(self._fallbacks))
        return RawConstraint(
            sql=' '.join((langcase, '<', langcase, 'OR ('
                          '%s.language_code = %s.language_code AND '
                          '%s.id < %s.id)')),
            aliases=(alias, related_alias,
                     alias, related_alias,
                     alias, related_alias)
        )

    @minimumDjangoVersion(1, 8)
    def get_joining_columns(self):
        return ((self._master, self._master), )

#===============================================================================
# Field for translation navigation
#===============================================================================

class LanguageConstraint(object):
    def __init__(self, col):
        self.col = col

    def as_sql(self, compiler, connection):
        qn = compiler.quote_name_unless_alias
        col_sql, col_params = self.col.as_sql(compiler, connection)
        return (
            '%s = %s.%s' % (col_sql, qn(compiler.query.get_initial_alias()), qn('language_code')),
            col_params
        )

class SingleTranslationObject(ForeignObject):
    requires_unique_target = False

    def __init__(self, model, translations_model=None):
        self.shared_model = model
        if translations_model is None:
            translations_model = model._meta.translations_model
        super(SingleTranslationObject, self).__init__(
            translations_model,
            from_fields=['id'], to_fields=['master'],
            null=True,
            auto_created=True,
            editable=False,
            related_name='+',
            on_delete=models.DO_NOTHING,
        )

    def get_cache_name(self):
        return self.shared_model._meta.translations_cache

    def get_extra_restriction(self, where_class, alias, related_alias):
        related_model = self.related_model if django.VERSION >= (1, 8) else self.rel.to
        return LanguageConstraint(
            Col(alias, related_model._meta.get_field('language_code'), models.CharField())
        )

    def get_path_info(self):
        path = super(SingleTranslationObject, self).get_path_info()
        return [path[0]._replace(direct=False)]

    def contribute_to_class(self, cls, name, virtual_only=False):
        super(SingleTranslationObject, self).contribute_to_class(cls, name, False)
        delattr(cls, self.name)

    def deconstruct(self):
        name, path, args, kwargs = super(SingleTranslationObject, self).deconstruct()
        args = (
            "%s.%s" % (self.shared_model._meta.app_label,
                       self.shared_model._meta.object_name),
            kwargs['to'],
        )
        kwargs = {}
        return name, path, args, kwargs

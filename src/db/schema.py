from ast import In
import datetime

import configs.creds as creds
import enum

#SQLAlchemy
import sqlalchemy
import sqlalchemy.orm
import sqlalchemy.ext.declarative
from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Text, Date, Time, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.orm import deferred

DATABASE_NAME = creds.database_name
SQL_URL = "mysql+mysqlconnector://%s:%s@sql.mit.edu/%s?charset=utf8" % (
    creds.user, creds.password, DATABASE_NAME
)

# 08-05-2023: We've been having issues with Scripts MySQL server, so let's create a local
#             SQLite3 database for now.
# (TODO): Get Scripts MySQL working with large packet size (> 1 MB)

SQL_URL = 'sqlite:///dormdigest-prod.db' # Local directory

#Defines length (in characters) of common data types

EMAIL_LENGTH = 64
EMAIL_MESSAGE_ID_LENGTH = 512 #Per RFC-2822 regulation
EMAIL_IN_REPLY_TO = 512
EVENT_LINK_LENGTH = 512
CLUB_NAME_LENGTH = 128
CLUB_NAME_ABBREV_LENGTH = 32
EMAIL_DESCRIPTION_CHUNK_SIZE = 65000 # bytes
SESSION_ID_LENGTH = 32

class UserPrivilege(enum.Enum):
    NORMAL = 0 #Default
    ADMIN = 1
    
class MemberPrivilege(enum.Enum):
    NORMAL = 0 #Default
    OFFICER = 1
    
class EventDescriptionType(enum.Enum):
    PLAINTEXT = 0
    HTML = 1


##############################################################
# Setup Stages
##############################################################

# Initialization Steps
SQLBase = sqlalchemy.ext.declarative.declarative_base()
sqlengine = sqlalchemy.create_engine(SQL_URL,pool_recycle=600,pool_pre_ping=True)
SQLBase.metadata.bind = sqlengine

# Main primitives
class Event(SQLBase):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True,
                unique=True, autoincrement=True)

    # User that submitted the event (can be only one!)
    user_id = Column(Integer, ForeignKey("users.id"),nullable=False)
    user = relationship("User")
    
    # Event characteristics
    title = Column(String(256))
    club_id = Column(Integer, ForeignKey("clubs.id"))
    club = relationship("Club")
    
    location = Column(String(128), default="")
    
    # Note: Descriptions are stored in EventDescription
    # description = deferred(Column(Text, default=""), group="full_description")
    # description_html = deferred(Column(Text, default=""), group="full_description")

    tags = relationship('EventTag', backref='Event', lazy='dynamic')

    cta_link = Column(String(EVENT_LINK_LENGTH))
    start_date = Column(Date)
    end_date = Column(Date)
    start_time = Column(Time)
    end_time= Column(Time)

    # Published and approved?
    approved_is = Column(Boolean, default=False)

    date_created = Column(DateTime, default=datetime.datetime.now)
    date_updated = Column(DateTime, default=datetime.datetime.now)

    def get_time_and_date(self):
        datetime_json = {            
            'start_date': (self.start_date.isoformat()) if self.start_date else None,
            'end_date': (self.end_date.isoformat()) if self.end_date else None,
            'start_time': (self.start_time.isoformat()+"Z") if self.start_time else None,
            'end_time': (self.end_time.isoformat()+"Z") if self.end_time else None,
        }
        return datetime_json

    def json(self, fullJSON=2):
        additionalJSON = {}
        if (fullJSON == 2):
            additionalJSON = {
                'desc': self.description,
                'desc_html': self.description_html
            }
        elif (fullJSON == 1):
            additionalJSON = {
                'desc': self.description[:100] + "..." if self.description else ""
            }

        return {
            'title': self.title,
            'location': self.location,
            'link': self.cta_link,
            'approved': self.approved_is,
            'id': self.id,
            **(self.get_time_and_date())
            **additionalJSON
        }

    def serialize(self):
        return {
            "name": self.title,
            "location": self.location,
            "description": self.description_html if self.description_html else self.description,
            "description_text": self.description,
            **(self.get_time_and_date())
        }

class User(SQLBase):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True,
                unique=True, autoincrement=True)

    email = Column(String(EMAIL_LENGTH), unique=True, nullable=False)
    user_privilege = Column(Integer, default=0)

    date_created = Column(DateTime, default=datetime.datetime.now)
    date_updated = Column(DateTime, default=datetime.datetime.now)

    def __init__(self, email,user_privilege):
        self.email = email
        self.user_privilege = user_privilege

    def json(self):
        return {
            'email': self.email,
            'user_privilege': self.user_privilege
        }
    def get_user_email(self):
        return self.email

class Club(SQLBase): 
    __tablename__ = "clubs"
    id = Column(Integer, primary_key=True,
            unique=True, autoincrement=True)
    name = Column(String(CLUB_NAME_LENGTH), unique=True,nullable=False)
    abbrev = Column(String(CLUB_NAME_ABBREV_LENGTH))
    exec_email = Column(String(EMAIL_LENGTH))
    
    def __init__(self, name, abbrev=None, exec_email=None):
        self.name = name
        self.abbrev = abbrev
        self.exec_email = exec_email

# Relationship Tables
class ClubMembership(SQLBase): #Map user to clubs they are in
    __tablename__ = "club_memberships"
    id = Column(Integer, primary_key=True,
            unique=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"),nullable=False)
    club_id = Column(Integer, ForeignKey("clubs.id"), nullable=False)
    member_privilege = Column(Integer, default=0)
    
    def __init__(self, user_id, club_id, member_privilege=0):
        self.user_id = user_id
        self.club_id = club_id
        self.member_privilege = member_privilege

class EventTag(SQLBase): #Map event to tags it is associated with
    __tablename__ = "event_tags"
    id = Column(Integer, primary_key=True,unique=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"),nullable=False)
    event_tag = Column(Integer, default=0)
    
    def __init__(self, event_id, event_tag):
        self.event_id = event_id
        self.event_tag = event_tag
        
    def get_tag_value(self):
        return self.event_tag

class EventDescription(SQLBase): # Contain email description content for a specific Event
    __tablename__ = "event_descriptions"
    id = Column(Integer, primary_key=True,unique=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("events.id"))
    content_type = Column(Integer) # Enum value denoting plaintext or html
    content_index = Column(Integer) # For maintain ordering of text
    data = Column(String(EMAIL_DESCRIPTION_CHUNK_SIZE), default="") # When storing, need to be < 1 MB to avoid  
                                                                    # SQL max_allowed_packet limits
    
    def __init__(self, event_id, content_type, content_index, data):
        self.event_id = event_id
        self.content_type = content_type
        self.content_index = content_index
        self.data = data

class SessionId(SQLBase): # keep track of valid session ids
    __tablename__ = "session_ids"
    id = Column(Integer, primary_key=True,unique=True, autoincrement=True)
    session_id = Column(String(SESSION_ID_LENGTH), nullable=False)
    email_addr = Column(String(EMAIL_LENGTH), unique=False, nullable=False)
    date_created = Column(DateTime, default=datetime.datetime.now)

    def __init__(self, session_id, email_addr):
        self.session_id = session_id
        self.email_addr = email_addr

# Implement schema
SQLBase.metadata.create_all(sqlengine)